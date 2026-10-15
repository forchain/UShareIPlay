"""在线用户抽屉深模块的离线单测。

被测的是 `OnlineDrawerManager` 的会话契约（`drawer_session` / `resolve_visible_username`）
与驱动端口契约，不碰任何 Appium 时序：真实屏幕在这里整块换成了
`tests/fakes/in_memory_online_drawer_driver.py`。

这些断言保护的是 spec #426 的问题陈述 #1：**无人认领的抽屉生命周期**。因此本文件里
最要紧的不是「抽屉能不能打开」，而是三条归属规则 —— 只关自己打开的那一次、正文抛
异常时照样收尾、任何路径下都不许出现盲按返回（盲按返回会退出派对房间）。
"""

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ushareiplay.managers.online_drawer import (
    OnlineDrawerDriverPort,
    OnlineDrawerManager,
    SoulOnlineDrawerDriver,
)
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


class _FakeController:
    """最小 UI 独占替身。

    用真的 `asyncio.Lock`（而不是 bool 标记），这样「会话期间锁确实被持有」是
    可观测的事实，而不是替身自己声称的事实。
    """

    def __init__(self):
        self.ui_lock = asyncio.Lock()
        self.reasons = []

    @asynccontextmanager
    async def ui_session(self, reason: str = ""):
        self.reasons.append(reason)
        async with self.ui_lock:
            yield


def _make_manager(driver=None, *, controller=None, name_resolver=None, handler=None):
    """装配一个受保护单例实例（ADR-0009：只能经 initialize 创建）。"""
    fake_handler = handler
    if fake_handler is None:
        fake_handler = SimpleNamespace(
            logger=None,
            controller=controller if controller is not None else _FakeController(),
        )
    return OnlineDrawerManager.initialize(
        handler=fake_handler,
        driver=driver,
        name_resolver=name_resolver,
    )


# ---------------------------------------------------------------------------
# 会话生命周期
# ---------------------------------------------------------------------------


async def test_session_opens_settles_then_closes_in_order():
    """正常退出：打开 -> 落定 -> 正文 -> 关闭，且抽屉回到关闭状态。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明", "小红"], journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="test:normal") as open_error:
        assert open_error is None
        journal.append("body")

    assert journal == ["drawer:open", "drawer:settle", "body", "drawer:close"]
    assert driver.drawer_open is False


async def test_session_yields_open_error_and_does_not_close_when_open_failed():
    """打不开抽屉：正文拿到 error dict，且不去关闭一个自己没打开的抽屉。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], open_fails=True, journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="test:open-fails") as open_error:
        assert isinstance(open_error, dict)
        assert "error" in open_error
        journal.append("body")

    assert "drawer:close" not in journal
    assert driver.drawer_open is False


async def test_session_does_not_close_a_drawer_that_was_already_open():
    """进场时抽屉已经开着：不夺取归属，退出后保持原状，交给外层决定何时关。

    这是「只关自己打开的那一次」的全部意义：#432 迁移在线名单抓取时，抽屉会话会
    互相嵌套，谁也不该把别人的抽屉关掉。
    """
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], drawer_open=True, journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="test:already-open") as open_error:
        assert open_error is None
        journal.append("body")

    assert journal == ["body"]
    assert driver.drawer_open is True


async def test_session_closes_when_body_raises_and_lets_it_propagate():
    """正文抛异常：照样收尾，然后让异常继续往外走。

    没有这条 finally，抽屉就会悬在屏幕上，等下一次盲按返回把它和房间一起带走。
    """
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], journal=journal)
    manager = _make_manager(driver)

    with pytest.raises(RuntimeError, match="正文炸了"):
        async with manager.drawer_session(reason="test:raises") as open_error:
            assert open_error is None
            journal.append("body")
            raise RuntimeError("正文炸了")

    assert journal == ["drawer:open", "drawer:settle", "body", "drawer:close"]
    assert driver.drawer_open is False


async def test_session_closes_when_body_raises_even_for_a_drawer_it_did_not_open():
    """抽屉不是本会话打开的，正文抛异常也不越权去关 —— 归属只属于外层。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], drawer_open=True)
    manager = _make_manager(driver)

    with pytest.raises(RuntimeError):
        async with manager.drawer_session(reason="test:raises-not-mine"):
            raise RuntimeError("正文炸了")

    assert driver.drawer_open is True
    assert driver.close_calls == 0


async def test_session_yields_error_and_closes_when_settle_fails():
    """抽屉开了却没落定：这是本会话打开的，必须收尾，绝不留一个半开的抽屉。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], settle_fails=True, journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="test:settle-fails") as open_error:
        assert isinstance(open_error, dict)
        assert "error" in open_error
        journal.append("body")

    # with 正文一定会被进入（上下文管理器不替你 return），但拿到的 open_error
    # 已经在它之前就把抽屉收走了：调用方看到 error 就直接 return，不做无用功。
    assert journal == ["drawer:open", "drawer:close", "body"]
    assert driver.drawer_open is False


# ---------------------------------------------------------------------------
# 关不掉时：记警告，不抛，不退房间
# ---------------------------------------------------------------------------


async def test_close_failure_is_logged_and_does_not_raise_out_of_the_session(caplog):
    """两个 ivClose 都点不到：记一条警告、保持原状，绝不把异常抛给调用方。

    抽屉留在屏幕上只是难看一次；抛出去会让一次正常的命令变成任务失败，而用
    `press_back` 去「救」它会直接退出派对房间。
    """
    driver = InMemoryOnlineDrawerDriver(members=["小明"], close_fails=True)
    manager = _make_manager(driver)

    with caplog.at_level(logging.WARNING):
        async with manager.drawer_session(reason="test:close-fails") as open_error:
            assert open_error is None

    assert any("未能通过 ivClose" in r.message for r in caplog.records)
    assert driver.drawer_open is True


async def test_close_failure_during_error_cleanup_does_not_mask_the_original_error(caplog):
    """正文抛异常且同时关不掉抽屉：警告归警告，原异常原样往外走。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], close_fails=True)
    manager = _make_manager(driver)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="正文炸了"):
            async with manager.drawer_session(reason="test:close-fails-and-raises"):
                raise RuntimeError("正文炸了")

    assert any("未能通过 ivClose" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 盲按返回的禁令（spec #426 问题陈述 #1）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "driver_kwargs, body",
    [
        ({}, None),                                   # 正常退出
        ({}, "raise"),                                # 正文抛异常
        ({"open_fails": True}, None),                 # 打不开
        ({"drawer_open": True}, None),                # 进场时就开着
        ({"settle_fails": True}, None),               # 开了但没落定
        ({"close_fails": True}, None),                # 关不掉
    ],
)
async def test_no_back_press_ever_happens_on_any_path(driver_kwargs, body):
    """无论走哪条路径，事件流里都不该出现一次盲按返回。

    旧实现在关不掉时会 `press_back` 再点遮罩，而盲按返回会误退出派对房间
    （真机 09-28）。这条断言是那张账单的直接防线。
    """
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], journal=journal, **driver_kwargs)
    manager = _make_manager(driver)

    if body == "raise":
        with pytest.raises(RuntimeError):
            async with manager.drawer_session(reason="test:no-back"):
                raise RuntimeError("正文炸了")
    else:
        async with manager.drawer_session(reason="test:no-back"):
            pass

    assert not any("back" in event for event in journal), journal


def test_the_port_has_no_back_press_primitive_at_all():
    """结构上的保证：端口里根本没有 press_back，drawer_session 就**不可能**发它。

    只靠「记得别按返回」这种约定约束不住一个赶时间的修改；端口里没有这个方法，
    约束力来自接口本身。

    （对照：房间档案的端口**保留**了 `press_back`，因为那个抽屉关不掉时已经确认
    自己还在派对房间里，而在线用户抽屉没有这层证据。）
    """
    assert not hasattr(OnlineDrawerDriverPort, "press_back")
    for adapter_class in (SoulOnlineDrawerDriver, InMemoryOnlineDrawerDriver):
        assert not hasattr(adapter_class, "press_back"), adapter_class.__name__


# ---------------------------------------------------------------------------
# UI 独占
# ---------------------------------------------------------------------------


async def test_ui_lock_is_held_for_the_whole_session_and_released_after():
    """打开、落定、找行、关闭全程持锁，退出后释放。

    不持锁时 EventManager 的兜底 `press_back` 会在这些 await 点把抽屉当成未知
    页面关掉 —— 正好是本模块要消灭的那种退房。这里读的是替身里那个真的
    `asyncio.Lock`，不是替身自己声称的「我加过锁了」。
    """
    controller = _FakeController()
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = _make_manager(driver, controller=controller)

    assert controller.ui_lock.locked() is False

    async with manager.drawer_session(reason="event:refresh_online_users") as open_error:
        assert open_error is None
        assert controller.ui_lock.locked() is True

    assert controller.ui_lock.locked() is False
    assert controller.reasons == ["event:refresh_online_users"]


async def test_ui_lock_is_released_even_when_the_body_raises():
    """正文抛异常时锁也必须还回去，否则一次失败就让后续 UI 操作永远排队。"""
    controller = _FakeController()
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = _make_manager(driver, controller=controller)

    with pytest.raises(RuntimeError):
        async with manager.drawer_session(reason="test:lock-on-raise"):
            assert controller.ui_lock.locked() is True
            raise RuntimeError("正文炸了")

    assert controller.ui_lock.locked() is False


async def test_session_still_works_when_no_controller_is_wired():
    """controller 缺席（离线装配）时退化为不加锁，而不是抛错。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = OnlineDrawerManager.initialize(
        handler=SimpleNamespace(logger=None, controller=None), driver=driver
    )

    async with manager.drawer_session(reason="test:no-controller") as open_error:
        assert open_error is None


# ---------------------------------------------------------------------------
# 两个命名域：DB canonical 名 vs Soul UI 可见昵称
# ---------------------------------------------------------------------------


async def test_resolve_visible_username_uses_the_injected_resolver():
    """canonical 名（主账号）经解析器换成 UI 上的分身名。

    房间里只有 UI 名字是可用坐标：在线列表按屏幕上显示的文本找人。两个命名域
    的字符串**不同**，拿 canonical 名直接 `==` UI 文本永远不成立。
    """
    seen = []

    async def resolver(username):
        seen.append(username)
        return {"forchain": "链子"}.get(username, username)

    manager = _make_manager(
        InMemoryOnlineDrawerDriver(), name_resolver=resolver
    )

    assert await manager.resolve_visible_username("forchain") == "链子"
    # 已经在 UI 域里的名字原样通过，不会被二次翻译。
    assert await manager.resolve_visible_username("链子") == "链子"
    assert seen == ["forchain", "链子"]


async def test_resolve_visible_username_is_identity_without_a_resolver():
    """没有注入解析器时按恒等处理 —— 那时调用方给的名字本来就是 UI 文本。"""
    manager = _make_manager(InMemoryOnlineDrawerDriver())

    assert await manager.resolve_visible_username("小明") == "小明"
    assert await manager.resolve_visible_username("") == ""


async def test_canonical_name_must_be_resolved_before_searching_the_drawer():
    """端到端串一遍：canonical 名 -> 可见昵称 -> 在抽屉里找得到那一行。

    这是本 ticket 要交付的那条完整接线；名字解析错一次，抽屉里就永远找不到人。
    """
    driver = InMemoryOnlineDrawerDriver(members=[("链子", "密友"), ("小红", None)])

    async def resolver(username):
        return {"forchain": "链子"}.get(username, username)

    manager = _make_manager(driver, name_resolver=resolver)

    async with manager.drawer_session(reason="test:naming-domains") as open_error:
        assert open_error is None
        visible = await manager.resolve_visible_username("forchain")
        row = await driver.find_member_row(visible)

    assert row is not None
    assert row.visible_name == "链子"
    assert row.follow_state == "密友"
    # 反证：直接拿 canonical 名去找，在抽屉里是找不到的。
    assert await driver.find_member_row("forchain") is None


# ---------------------------------------------------------------------------
# 端口契约：两个适配器必须遵守同一份签名
# ---------------------------------------------------------------------------

#: 端口的全部原语。两个适配器都逐个对得上，替身才不会悄悄漂移成另一套接口 ——
#: 那会让「离线的单测通过」变成一句谎话。
PORT_METHODS = (
    "is_open",
    "open",
    "close",
    "wait_for_settle",
    "scroll_container",
    "find_member_row",
    # #432 在线名单抓取要的三条读数：人数、整页行、到底提示。
    "read_online_count",
    "visible_member_rows",
    "is_at_end",
)

ADAPTER_CLASSES = (SoulOnlineDrawerDriver, InMemoryOnlineDrawerDriver)


@pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
def test_adapter_implements_the_whole_port(adapter_class):
    assert issubclass(adapter_class, OnlineDrawerDriverPort)
    # 一个没实现完的 ABC 是实例化不了的；这里显式断言，避免有人把抽象方法删掉。
    assert not getattr(adapter_class, "__abstractmethods__", frozenset())
    for method_name in PORT_METHODS:
        assert callable(getattr(adapter_class, method_name)), method_name


@pytest.mark.parametrize("method_name", PORT_METHODS)
def test_both_adapters_have_identical_signatures_to_the_port(method_name):
    """参数名、关键字限定、默认值、返回标注必须逐字一致。

    签名漂移比行为漂移更阴险：调用点先坏，而且坏在测试之外的地方。
    """
    port_signature = inspect.signature(getattr(OnlineDrawerDriverPort, method_name))
    for adapter_class in ADAPTER_CLASSES:
        adapter_signature = inspect.signature(getattr(adapter_class, method_name))
        assert adapter_signature == port_signature, adapter_class.__name__


# ---------------------------------------------------------------------------
# 生产适配器：手势必须与既有在线名单抓取逐字一致
# ---------------------------------------------------------------------------


class _StubElement:
    """最小 WebElement 替身：只带适配器真正读得到的属性。"""

    def __init__(self, text="", location=None, size=None, displayed=True):
        self.text = text
        self.location = location or {"x": 0, "y": 0}
        self.size = size or {"width": 0, "height": 0}
        self.displayed = displayed
        self.clicked = False

    def click(self):
        self.clicked = True

    def is_displayed(self):
        return self.displayed


class _StubFinder:
    """按元素 key 服务的屏幕替身，并记录每次查找。"""

    def __init__(self, screen=None, children=None):
        self.screen = screen or {}
        self.children = children or {}
        self.looked_up = []

    def try_find_element(self, key, log=False, clickable=False):
        self.looked_up.append(key)
        return self.screen.get(key)

    def wait_for_element(self, key, timeout=10):
        self.looked_up.append(key)
        return self.screen.get(key)

    def wait_for_element_clickable(self, key, timeout=10):
        self.looked_up.append(key)
        return self.screen.get(key)

    def wait_for_element_disappear(self, key, timeout=10, poll_frequency=None):
        pass

    def find_child_elements(self, parent, key):
        return list(self.children.get((parent, key), []))

    def find_child_element(self, parent, key, log_failure=True):
        return self.children.get((parent, key))


class _StubGesture:
    def __init__(self, works=True):
        self.swipes = []
        self.works = works

    def swipe(self, x1, y1, x2, y2, duration_ms=600):
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        return self.works


class _ExplodingKeyActions:
    """一旦被按返回就当场失败。

    旧实现在关不掉抽屉时会走 `press_back`，而盲按返回会误退出派对房间
    （spec #426 问题陈述 #1）。这里让它没有机会「顺手兜底」。
    """

    def press_back(self):
        raise AssertionError("盲按返回会误退出派对房间，不得出现在抽屉收尾路径上")


def _make_soul_adapter(finder, gesture=None):
    handler = SimpleNamespace(
        logger=None,
        element_finder=finder,
        gesture_handler=gesture or _StubGesture(),
        key_actions=_ExplodingKeyActions(),
    )
    return SoulOnlineDrawerDriver(handler)


@pytest.fixture(autouse=True)
def _no_settle_sleep(monkeypatch):
    """离线的单测里没有真机，落定静默直接去掉（时序本身不是这里要断言的东西）。"""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(
        "ushareiplay.managers.online_drawer.soul_driver.asyncio.sleep", _instant
    )


async def test_production_open_clicks_the_user_count_entry():
    """打开 = 点 `user_count` 入口，与旧 `_scrape_online_user_names` 的前两步一致。"""
    entry = _StubElement(text="6人")
    finder = _StubFinder(screen={"user_count": entry})
    driver = _make_soul_adapter(finder)

    assert await driver.open(error_message="打不开") == {}
    assert entry.clicked is True


async def test_production_open_reports_the_callers_error_message_when_entry_is_absent():
    """入口读不到：返回调用方自己的文案，让聊天气泡里的报错保持原样。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.open(error_message="打不开在线用户列表") == {
        "error": "打不开在线用户列表"
    }


async def test_production_close_clicks_iv_close_and_never_presses_back():
    """关闭只点 `ivClose`；`key_actions` 就在旁边也不会被碰。"""
    close_btn = _StubElement()
    finder = _StubFinder(screen={"online_users_close": close_btn})
    driver = _make_soul_adapter(finder)

    assert await driver.close() is True
    assert close_btn.clicked is True


async def test_production_close_falls_back_to_the_second_close_key():
    """第一个 key 没渲染出来时按顺序试第二个，两个都指向 `ivClose`。"""
    fallback_btn = _StubElement()
    finder = _StubFinder(screen={"close_button": fallback_btn})
    driver = _make_soul_adapter(finder)

    assert await driver.close() is True
    assert fallback_btn.clicked is True


async def test_production_close_returns_false_when_both_close_keys_are_missing():
    """两个按钮都没有：如实返回 False，让调用方决定，绝不自己换成按返回。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.close() is False


async def test_production_scroll_uses_container_geometry_at_the_slow_duration():
    """滑动坐标由容器的 location/size 算出，时长 800ms（避免惯性飞滚跳过未渲染行）。"""
    container = _StubElement(location={"x": 100, "y": 200}, size={"width": 500, "height": 800})
    gesture = _StubGesture()
    driver = _make_soul_adapter(
        _StubFinder(screen={"online_users": container}), gesture
    )

    assert await driver.scroll_container() is True
    # 中心 x=350；手指从 0.75 高度(800) 划到 0.30 高度(440)。
    assert gesture.swipes == [(350, 800, 350, 440, 800)]


async def test_production_find_member_row_matches_the_visible_nickname():
    """按 UI 可见昵称匹配，并带出关注关系文案。"""
    container = _StubElement()
    row = _StubElement()
    name_elem = _StubElement(text="链子")
    follow_elem = _StubElement(text="密友")
    finder = _StubFinder(
        screen={"online_users": container},
        children={
            (container, "user_container"): [row],
            (row, "online_user"): name_elem,
            (row, "follow_state"): follow_elem,
        },
    )
    driver = _make_soul_adapter(finder)

    found = await driver.find_member_row("链子")
    assert found is not None
    assert found.visible_name == "链子"
    assert found.follow_state == "密友"
    # 找不到的人返回 None，元素对象一个也不外泄。
    assert await driver.find_member_row("查无此人") is None


async def test_production_adapter_fails_gracefully_without_a_handler():
    """没有 handler 时每个动作都以「App 不可用」失败，而不是抛 AttributeError。

    与 `SoulDrawerDriver._require_handler` 同一份纪律：离线装配与半启动状态下
    都要能问出答案，而不是把调用方炸掉。
    """
    driver = SoulOnlineDrawerDriver(None)

    assert await driver.is_open() is False
    assert await driver.open(error_message="打不开") == {"error": "打不开"}
    assert await driver.close() is False
    assert await driver.wait_for_settle() is False
    assert await driver.scroll_container() is False
    assert await driver.find_member_row("链子") is None
    # #432 起在线名单抓取还需要的三个读数，同样必须能问出答案。
    assert await driver.read_online_count() is None
    assert await driver.visible_member_rows() == []
    assert await driver.is_at_end() is False


# ---------------------------------------------------------------------------
# #432 追加的三个读数：人数、整页行、到底提示
# ---------------------------------------------------------------------------


async def test_production_read_online_count_parses_the_first_digit_run():
    """「N 人在线」控件里的第一段数字就是房间报的在线人数。

    正则解析属于 Appium 文本细节，止步在适配器：引擎拿到的是 int 或 None，
    不该知道控件文案长什么样。
    """
    driver = _make_soul_adapter(_StubFinder(screen={"user_count": _StubElement(text="6人在线")}))

    assert await driver.read_online_count() == 6


async def test_production_read_online_count_is_none_when_unreadable():
    """控件读不到、或文案里根本没有数字时都是 None —— 没有人数不等于人数为 0。"""
    assert await _make_soul_adapter(_StubFinder(screen={})).read_online_count() is None
    assert (
        await _make_soul_adapter(
            _StubFinder(screen={"user_count": _StubElement(text="在线")})
        ).read_online_count()
        is None
    )


async def test_in_memory_read_online_count_returns_the_screened_count():
    """替身如实报告房间里那个控件写了多少人；控件不存在时是 None。"""
    assert await InMemoryOnlineDrawerDriver(online_count=6).read_online_count() == 6
    assert await InMemoryOnlineDrawerDriver(online_count=None).read_online_count() is None


async def test_production_visible_member_rows_reads_every_rendered_row():
    """整页行一次读回：昵称与关注关系都在适配器里取好，行对象不外泄。"""
    rows = [_StubElement(), _StubElement()]
    alice = _StubElement(text="alice")
    bob = _StubElement(text="bob")
    bob_follow = _StubElement(text="我关注的")
    container = _StubElement()
    finder = _StubFinder(
        screen={"online_users": container},
        children={
            (container, "user_container"): rows,
            (rows[0], "online_user"): alice,
            (rows[0], "follow_state"): _StubElement(text="密友"),
            (rows[1], "online_user"): bob,
            (rows[1], "follow_state"): bob_follow,
        },
    )
    driver = _make_soul_adapter(finder)

    read = await driver.visible_member_rows()

    assert [row.visible_name for row in read] == ["alice", "bob"]
    assert [row.follow_state for row in read] == ["密友", "我关注的"]


async def test_production_visible_member_rows_skips_broken_rows_and_missing_containers():
    """读坏的单行不影响整页（滑动中行会失效是常态）；容器读不到就是空页。"""
    good_row = _StubElement()
    container = _StubElement()
    finder = _StubFinder(
        screen={"online_users": container},
        children={
            (container, "user_container"): [_StubElement(), good_row],
            (good_row, "online_user"): _StubElement(text="小明"),
        },
    )
    driver = _make_soul_adapter(finder)

    read = await driver.visible_member_rows()

    assert [row.visible_name for row in read] == ["小明"]
    assert read[0].follow_state is None
    assert await _make_soul_adapter(_StubFinder(screen={})).visible_member_rows() == []


async def test_in_memory_visible_member_rows_only_returns_the_current_page():
    """替身只给当前窗口的行：翻页是引擎的循环决策，不在读数里偷做。"""
    driver = InMemoryOnlineDrawerDriver(
        members=[("alice", "密友"), ("bob", None), ("cathy", "关注了我")], page_size=2
    )

    assert [row.visible_name for row in await driver.visible_member_rows()] == ["alice", "bob"]
    await driver.scroll_container()
    assert [row.visible_name for row in await driver.visible_member_rows()] == ["cathy"]


async def test_production_is_at_end_requires_the_hint_to_be_displayed():
    """到底提示必须是**已显示**的：元素还留在 dump 里不代表用户看得见它。"""
    shown = _StubElement(text="没有更多了")
    hidden = _StubElement(text="没有更多了", displayed=False)

    assert await _make_soul_adapter(
        _StubFinder(screen={"no_more_data": shown})
    ).is_at_end() is True
    assert await _make_soul_adapter(
        _StubFinder(screen={"no_more_data": hidden})
    ).is_at_end() is False
    assert await _make_soul_adapter(_StubFinder(screen={})).is_at_end() is False


async def test_in_memory_is_at_end_follows_the_end_of_the_list():
    """滑到最后一行之后到底提示才亮；`end_hint=False` 的列表永远不到底。"""
    driver = InMemoryOnlineDrawerDriver(members=["alice", "bob", "cathy"], page_size=2)

    assert await driver.is_at_end() is False
    await driver.scroll_container()
    assert await driver.is_at_end() is True

    never = InMemoryOnlineDrawerDriver(
        members=["alice", "bob", "cathy"], page_size=2, end_hint=False
    )
    await never.scroll_container()
    assert await never.is_at_end() is False

