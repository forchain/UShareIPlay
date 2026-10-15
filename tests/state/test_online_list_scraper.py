"""在线名单抓取的离线单测：抓取只在 `OnlineDrawerManager.drawer_session` 里发生。

被测的是 `OnlineListScraper.refresh_online_users` 的对外行为：抓到哪些人、等级怎么
映射、`PresenceTracker` 有没有更新、人数对不上时重试几次、每一条退出路径上抽屉是不是
都被收走了。真实屏幕整块换成 `tests/fakes/in_memory_online_drawer_driver.py`，因此这里
没有任何 Appium 元素、坐标或手势时序 —— 那些是端口后面适配器的事。

这些断言保护的是在线名单抓取原有的行为契约，尤其是两条容易在迁移中丢掉的：

1. **翻页抓全**：一页一页往下读，四个终止条件（到底提示 / 达到目标人数 / 连续多轮没有
   新人 / 滑够次数 / 滑不动）各管各的；
2. **一定要收尾**：正常抓完、提前停下、翻页途中炸了，抽屉都必须关掉，且只关会话自己
   打开的那一次。
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.managers.online_drawer import OnlineDrawerManager
from ushareiplay.models import User
from ushareiplay.state import online_list_scraper as scraper_module
from ushareiplay.state.online_list_scraper import OnlineListScraper
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


class _ReentrantController:
    """最小 UI 独占替身，照抄生产 `AppController.ui_session` 的**可重入**语义。

    必须可重入：`refresh_online_users` 在最外层持锁，两次抓取各自再经由
    `drawer_session` 嵌套一次锁。生产实现用「持有者 task + 嵌套深度」放行嵌套
    （`asyncio.Lock` 本身不可重入）；这里用同一个办法，否则测的不是生产的接线。
    """

    def __init__(self):
        self.ui_lock = asyncio.Lock()
        self.reasons = []
        self._owner = None
        self._depth = 0

    @asynccontextmanager
    async def ui_session(self, reason: str = ""):
        self.reasons.append(reason)
        task = asyncio.current_task()
        if self._depth > 0 and self._owner is task:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        await self.ui_lock.acquire()
        self._owner = task
        self._depth = 1
        try:
            yield
        finally:
            self._owner = None
            self._depth = 0
            self.ui_lock.release()

    @property
    def locked(self) -> bool:
        return self.ui_lock.locked()


class _RecordingLogger:
    """按级别收日志：断言「哪些事件被记录」，而不是记录了多少行。"""

    def __init__(self):
        self.records = []

    def _log(self, level, msg):
        self.records.append((level, str(msg)))

    def info(self, msg):
        self._log("info", msg)

    def debug(self, msg):
        self._log("debug", msg)

    def warning(self, msg):
        self._log("warning", msg)

    def error(self, msg):
        self._log("error", msg)

    def critical(self, msg):
        self._log("critical", msg)

    def messages(self, level):
        return [msg for lvl, msg in self.records if lvl == level]

    def has(self, needle) -> bool:
        return any(needle in msg for _lvl, msg in self.records)


def _wire(driver, *, controller=None, room_count=None):
    """按组合根的方式接线：抽屉管理器拿到驱动与 handler，scraper 拿到同一个 handler。

    两者共用一个 handler 是有意义的：这样 `refresh_online_users` 持有的 UI 独占锁和
    `drawer_session` 持有的是同一把，生产里它们本来就是同一个 controller。
    """
    logger = _RecordingLogger()
    controller = controller if controller is not None else _ReentrantController()
    handler = SimpleNamespace(logger=logger, controller=controller)

    OnlineListScraper.reset_instance()
    OnlineDrawerManager.reset_instance()
    RoomState.reset_instance()
    PresenceTracker.reset_instance()

    scraper = OnlineListScraper.initialize(handler)
    OnlineDrawerManager.initialize(handler, driver=driver)

    room = RoomState.initialize()
    room._logger = logger
    if room_count is not None:
        room.user_count = room_count

    presence = PresenceTracker.initialize()
    presence._logger = logger

    return SimpleNamespace(
        scraper=scraper,
        driver=driver,
        controller=controller,
        room=room,
        presence=presence,
        logger=logger,
    )


@pytest.fixture(autouse=True)
def _no_retry_gap_sleep(monkeypatch):
    """重试前那 0.4s 的间隔在离线测试里没有意义，记下「此刻锁还在不在」即可。"""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(scraper_module.asyncio, "sleep", _instant)


# ---------------------------------------------------------------------------
# 抓取结果
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_scrapes_online_names_and_updates_presence():
    """抓到的人进 `PresenceTracker`，抓取返回成功。"""
    driver = InMemoryOnlineDrawerDriver(members=["alice", "bob"])
    wired = _wire(driver, room_count=2)

    assert await wired.scraper.refresh_online_users() is True
    assert wired.presence.get_online_users() == {"alice", "bob"}


@pytest.mark.asyncio
async def test_refresh_reads_the_room_count_before_opening_the_drawer():
    """人数必须在抽屉打开**之前**读：抽屉一盖，「N 人在线」那个控件就被挡住了。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(
        members=["alice", "bob"], online_count=2, journal=journal
    )
    wired = _wire(driver, room_count=2)

    await wired.scraper.refresh_online_users()

    assert journal[0] == "drawer:count:2"
    assert journal[1] == "drawer:open"


@pytest.mark.asyncio
async def test_refresh_gives_up_when_the_drawer_cannot_be_opened():
    """入口点不到（打不开抽屉）：不更新在线名单，返回 False，且不去关一个自己没打开的抽屉。"""
    driver = InMemoryOnlineDrawerDriver(members=["alice"], open_fails=True)
    wired = _wire(driver, room_count=1)

    assert await wired.scraper.refresh_online_users() is False
    assert wired.presence.get_online_users() == set()
    assert driver.open_calls == 1
    assert driver.close_calls == 0


# ---------------------------------------------------------------------------
# 翻页与四个终止条件
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_paginates_through_every_page_and_accumulates_names():
    """一行渲染不完时一页一页往下读，名字累积到全量，且每次都是 800ms 的慢滑。

    房间不报人数（`user_count` 与控件都是 None），因此这一次抓取不受对账重试影响，
    断言的就是纯粹的翻页。
    """
    members = ["小明", "小红", "链子", "阿飞", "圆圆"]
    driver = InMemoryOnlineDrawerDriver(members=members, page_size=2)
    wired = _wire(driver, room_count=None)

    assert await wired.scraper.refresh_online_users() is True
    assert wired.presence.get_online_users() == set(members)
    # 5 行 / 每页 2 行：滑两次之后第三页就是最后一页。
    assert len(driver.scroll_durations) == 2
    assert set(driver.scroll_durations) == {800}, "滑动时长必须是 800ms 的慢滑，否则会跳过未渲染的行"


@pytest.mark.asyncio
async def test_refresh_stops_when_the_end_of_list_hint_is_shown():
    """终止条件 1：列表到底的提示显示了，即使人数目标永远达不到也要停。"""
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红", "链子"], page_size=2, end_hint=True
    )
    wired = _wire(driver, room_count=None)

    assert await wired.scraper.refresh_online_users() is True
    assert wired.presence.get_online_users() == {"小明", "小红", "链子"}
    assert driver.at_end_reads >= 1, "到底提示必须被真正问过，而不是靠滑不动兜底"
    assert len(driver.scroll_durations) == 1


@pytest.mark.asyncio
async def test_refresh_stops_once_the_target_count_is_reached():
    """终止条件 2：已抓到的人数达到房间报的人数就收工，后面的人不再去翻。"""
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红", "链子", "阿飞"], page_size=2
    )
    wired = _wire(driver, room_count=2)

    assert await wired.scraper.refresh_online_users() is True
    assert wired.presence.get_online_users() == {"小明", "小红"}
    assert driver.scroll_durations == [], "已经够了就不该再滑"


@pytest.mark.asyncio
async def test_refresh_stops_after_two_rounds_without_new_users():
    """终止条件 3：列表滑得动却连续两轮没有新人（既没到底提示也没达到人数）时收工。"""
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红", "链子"], page_size=2, end_hint=False
    )
    wired = _wire(driver, room_count=None)

    assert await wired.scraper.refresh_online_users() is True
    assert wired.presence.get_online_users() == {"小明", "小红", "链子"}
    # 第 3 页开始就一直是同一行：滑到内容不再前进，再滑两轮没有新人就该停。
    assert len(driver.scroll_durations) == 3
    assert wired.logger.has("No new users found")


@pytest.mark.asyncio
async def test_refresh_stops_after_fifty_swipes_at_the_latest():
    """终止条件 4：每一页都还有新人、列表却始终读不到底时，最多滑 50 次就放弃。

    数据要够长（51 页），否则「连续两轮没有新人」会先一步收尾 —— 那条兜底本来就该
    在它之前生效。
    """
    members = [f"user{i:02d}" for i in range(102)]
    driver = InMemoryOnlineDrawerDriver(members=members, page_size=2, end_hint=False)
    wired = _wire(driver, room_count=None)

    assert await wired.scraper.refresh_online_users() is True
    assert wired.presence.get_online_users() == set(members)
    assert len(driver.scroll_durations) == 50
    assert wired.logger.has("Reached max_swipes")


@pytest.mark.asyncio
async def test_refresh_stops_when_a_swipe_fails_and_keeps_the_partial_list():
    """终止条件 5：手势失败就停止翻页；名单因此不完整，但仍以最大努力更新，不丢弃。

    人数对不上会触发一次重试（这是既有对账行为），所以这里看到两个会话。
    """
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红", "链子", "阿飞"],
        page_size=2,
        end_hint=False,
        swipe_fails=True,
    )
    wired = _wire(driver, room_count=4)

    assert await wired.scraper.refresh_online_users() is True
    assert wired.presence.get_online_users() == {"小明", "小红"}
    assert wired.logger.has("Swipe failed")
    # 两次抓取各失败一次滑动手势，其余动作一律没有。
    assert len(driver.scroll_durations) == 2


# ---------------------------------------------------------------------------
# 关注关系 -> 等级
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_follow_state_maps_to_the_user_level():
    """关注关系文案映射成等级：密友 3 / 我关注的 2 / 关注了我 1；没有关注关系就只建档。"""
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        driver = InMemoryOnlineDrawerDriver(
            members=[
                ("密友哥", "密友"),
                ("我关注的人", "我关注的"),
                ("关注我的人", "关注了我"),
                ("路人", None),
            ]
        )
        wired = _wire(driver, room_count=4)

        assert await wired.scraper.refresh_online_users() is True

        levels = {
            row["username"]: row["level"]
            for row in await User.all().values("username", "level")
        }
        assert levels == {
            "密友哥": 3,
            "我关注的人": 2,
            "关注我的人": 1,
            "路人": 0,
        }
        # 在座的人同样进了在线名单。
        assert wired.presence.get_online_users() == {
            "密友哥",
            "我关注的人",
            "关注我的人",
            "路人",
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a_repeated_row_is_only_recorded_once():
    """翻页时上一页的行还在屏幕上：重复出现的名字不得重复建档、重复升级等级。"""
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        driver = InMemoryOnlineDrawerDriver(
            members=[("小明", "密友"), ("小明", "密友"), ("小红", "我关注的")],
            page_size=2,
            end_hint=False,
        )
        wired = _wire(driver, room_count=2)

        assert await wired.scraper.refresh_online_users() is True

        assert await User.filter(username="小明").count() == 1
        assert wired.presence.get_online_users() == {"小明", "小红"}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# 人数对账与重试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_count_mismatch_retries_in_a_second_fresh_session():
    """抓到的名字数与房间人数对不上：换一个**全新**的抽屉会话重试一次。

    必须换新会话 —— 列表没法往回滚，重试只有从头滑一次才可能把漏掉的人补上。
    """
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红"], page_size=1, online_count=3
    )
    wired = _wire(driver, room_count=3)

    assert await wired.scraper.refresh_online_users() is True
    assert wired.presence.get_online_users() == {"小明", "小红"}
    assert driver.open_calls == 2, "重试必须是第二个会话，而不是复用已经滑到底的列表"
    assert driver.close_calls == 2
    # 两次抓取都从头完整翻了一遍：每页 1 行、共 2 行，各读 2 页。
    assert driver.rows_reads == 4
    assert len(driver.scroll_durations) == 2
    assert wired.logger.has("count mismatch")


@pytest.mark.asyncio
async def test_the_ui_lock_is_held_across_both_scrape_attempts():
    """UI 独占锁在最外层一次持有到底：两次抓取之间那 0.4s 间隔期间也不能被抢走。

    锁一旦在两次抓取之间松开，EventManager 的兜底 `press_back` 就可能在这半秒里把
    抽屉当成未知页面关掉 —— 所以外层这个 session 不能挪进单次抓取里。
    """
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红"], page_size=1, online_count=3
    )
    wired = _wire(driver, room_count=3)
    locked_during_gap = []

    async def _record_gap(_seconds):
        locked_during_gap.append(wired.controller.locked)

    with patch.object(scraper_module.asyncio, "sleep", _record_gap):
        await wired.scraper.refresh_online_users()

    assert driver.open_calls == 2, "两次抓取都在外层 session 之内"
    assert locked_during_gap == [True], "两次抓取之间的间隔期必须仍然持锁"
    assert wired.controller.locked is False, "整个刷新结束后锁要还回去"
    assert wired.controller.reasons[0] == "event:refresh_online_users"


@pytest.mark.asyncio
async def test_refresh_online_users_retries_and_succeeds_when_second_attempt_matches():
    """当首次获取人数对不上（例如滚动漏人）时，自动重试一次；若重试人数对上，则成功更新。"""
    wired = _wire(InMemoryOnlineDrawerDriver())
    wired.room.user_count = 2

    call_count = 0

    async def mock_scrape(expected_count):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"alice"}, 2
        return {"alice", "bob"}, 2

    with patch.object(wired.scraper, "_scrape_online_user_names", side_effect=mock_scrape):
        result = await wired.scraper.refresh_online_users()

    assert result is True
    assert call_count == 2
    assert wired.presence.get_online_users() == {"alice", "bob"}


@pytest.mark.asyncio
async def test_refresh_online_users_proceeds_with_best_effort_when_count_mismatches_after_retry():
    """当重试后人数依然对不上时，以最大努力将抓取到的名单更新至 PresenceTracker，不抛弃数据，并返回 True。"""
    wired = _wire(InMemoryOnlineDrawerDriver())
    wired.room.user_count = 2

    call_count = 0

    async def mock_scrape(expected_count):
        nonlocal call_count
        call_count += 1
        return {"alice"}, 2  # 始终只有 1 人，与 2 人不符

    with patch.object(wired.scraper, "_scrape_online_user_names", side_effect=mock_scrape):
        result = await wired.scraper.refresh_online_users()

    assert result is True
    assert call_count == 2
    # 更新已抓取到的在线用户
    assert wired.presence.get_online_users() == {"alice"}
    assert wired.logger.has("still mismatched after retry")


@pytest.mark.asyncio
async def test_refresh_online_users_respects_target_count_parameter():
    """传入 target_count 时优先比对该参数。"""
    wired = _wire(InMemoryOnlineDrawerDriver())
    wired.room.user_count = 10  # 房间缓存为 10，但本次事件传入 target_count=1

    async def mock_scrape(expected_count):
        assert expected_count == 1
        return {"alice"}, 1

    with patch.object(wired.scraper, "_scrape_online_user_names", side_effect=mock_scrape):
        result = await wired.scraper.refresh_online_users(target_count=1)

    assert result is True
    assert wired.presence.get_online_users() == {"alice"}


# ---------------------------------------------------------------------------
# 收尾：每一条退出路径上抽屉都要关掉
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_drawer_is_closed_after_a_complete_scan():
    """正常抓完：抽屉关闭，动作顺序是读人数 -> 打开 -> 落定 -> 读行 -> 关闭。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明", "小红"], journal=journal)
    wired = _wire(driver, room_count=2)

    await wired.scraper.refresh_online_users()

    assert journal == [
        "drawer:count:None",
        "drawer:open",
        "drawer:settle",
        "drawer:rows:2",
        "drawer:close",
    ]
    assert driver.drawer_open is False
    assert driver.close_calls == 1


@pytest.mark.asyncio
async def test_the_drawer_is_closed_when_the_scan_stops_early():
    """提前停下（人数够了）同样要关抽屉，而且后面的人一次都不去翻。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红", "链子", "阿飞"], page_size=2, journal=journal
    )
    wired = _wire(driver, room_count=2)

    await wired.scraper.refresh_online_users()

    assert journal[-1] == "drawer:close"
    assert driver.drawer_open is False
    assert driver.close_calls == 1
    assert "drawer:scroll" not in journal


@pytest.mark.asyncio
async def test_the_drawer_is_closed_when_pagination_raises():
    """翻页途中炸了：异常照样往外走给刷新流程处理，但抽屉必须已经收走。

    悬在屏幕上的抽屉会被下一次盲按返回带着一起退出派对房间。
    """
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红", "链子"], page_size=2, end_hint=False
    )
    wired = _wire(driver, room_count=3)
    first_page = await driver.visible_member_rows()
    driver.visible_member_rows = AsyncMock(
        side_effect=[first_page, RuntimeError("行读炸了")]
    )

    assert await wired.scraper.refresh_online_users() is False
    assert driver.drawer_open is False
    assert driver.close_calls == 1
    assert wired.controller.locked is False
    assert wired.logger.has("Error refreshing online users")


# ---------------------------------------------------------------------------
# 旧的私有关闭方法退役后的行为：关窗一律走抽屉会话
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closing_the_drawer_never_presses_back():
    """关窗只走 `ivClose`：整个刷新过程里不存在任何盲按返回。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(
        members=["小明", "小红"], online_count=3, journal=journal
    )
    wired = _wire(driver, room_count=3)

    await wired.scraper.refresh_online_users()

    assert not any("back" in event for event in journal), journal
    assert not hasattr(wired.scraper, "_close_online_users_dialog")
