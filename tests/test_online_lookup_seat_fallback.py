"""资料页定位统一从在线用户抽屉里找人（#435 迁入 `OnlineDrawerManager`）。

由于座位上不见得有所有人，而且座位观测缓存存在滞后，
因此资料页定位（:gift / :admin / 私聊等）永远统一走在线用户列表，
不通过座位去选择用户，避免误报「不走在线列表」或绕过在线抽屉。

这里被测的是 `UserManager` 在抽屉会话里的编排决策：**开不开抽屉、翻不翻页、
什么时候放弃、失败时把抽屉收到什么程度**。真实屏幕整块换成了
`tests/fakes/in_memory_online_drawer_driver.py`，因此这些断言与任何 Appium 时序无关。

命名域也是这里的一部分：调用方给的名字可能是 DB 的 canonical 名（主账号），而抽屉里
只有 UI 可见昵称（分身名）能定位到人。解析在 `UserManager` 内部完成，调用方不必知道
自己手里是哪一个。
"""

import pytest

from ushareiplay.managers.online_drawer import OnlineDrawerManager
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)
from ushareiplay.managers.user_manager import UserManager
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


@pytest.fixture(autouse=True)
def reset_singletons():
    SeatObservationManager.reset_instance()
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()


class _Handler:
    """最小 handler：抽屉会话只用到 logger，controller 缺席时不加锁。"""

    def __init__(self):
        self.logger = None


def _wire(driver=None, *, name_resolver=None, members=(), **driver_kwargs):
    """装好抽屉会话与 `UserManager`，把屏幕交给内存替身。

    同一个测试里可以反复调用：先拆掉上一套装配。单例只允许 initialize 一次
    （ADR-0009），所以重装之前必须先 reset。

    Args:
        driver: 已建好的替身；不给就按 `members` / `driver_kwargs` 现建一个。
    """
    driver = driver if driver is not None else InMemoryOnlineDrawerDriver(
        members=members, **driver_kwargs
    )
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    OnlineDrawerManager.initialize(handler=_Handler(), driver=driver, name_resolver=name_resolver)
    manager = UserManager.initialize(_Handler())
    return manager, driver


def _seat_user(nickname, seat_number=10):
    """把某人登记为在座（模拟座位观测缓存）。

    这条登记是**故意不起作用**的：`UserManager` 从来不读座位观测。它守的是「不要因为
    人在座位上就绕过在线列表」——座位上不见得有所有人，且缓存有滞后。
    """
    obs = SeatObservationManager.initialize(_Handler())
    obs.seats[seat_number] = SeatSlot(
        seat_number=seat_number, occupied=True, username=nickname, label="管理"
    )
    return obs


@pytest.mark.asyncio
async def test_existing_user_is_found_in_the_online_list():
    """人在在线列表里：翻到那一页、点开资料卡，按原样回报成功。"""
    manager, driver = _wire(members=["Joyer", "不约儿童🐏🐏", "Chainer"], page_size=2)

    result = await manager.open_user_profile("不约儿童🐏🐏")

    assert "error" not in result
    assert result.get("user") == "不约儿童🐏🐏"
    assert driver.card_open is True


@pytest.mark.asyncio
async def test_user_absent_from_the_online_list_reports_not_found_after_full_pagination():
    """列表里确实没有：翻到到底提示为止，如实回报未找到，且不留悬着的抽屉。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(
        members=["a", "b", "c", "d", "e", "f"], page_size=2, journal=journal
    )
    manager, _ = _wire(driver)

    result = await manager.open_user_profile("查无此人")

    assert result["error"] == "User not found in online users list"
    assert result["user"] == "查无此人"
    # 「翻到底」是真的翻了：每一页都查过，最后一次停在到底提示上。
    assert journal.count("drawer:scroll") >= 2
    assert driver.at_end_reads > 0
    # 失败路径必须收尾，否则抽屉会悬在屏幕上等着被下一次盲按返回带走。
    assert driver.drawer_open is False
    assert driver.card_open is False


@pytest.mark.asyncio
async def test_seated_user_is_still_looked_up_in_the_online_list():
    """即使在座位上，也必须在在线用户列表中查找并成功打开其资料卡。"""
    manager, driver = _wire(members=["Joyer", "不约儿童🐏🐏"])
    _seat_user("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("不约儿童🐏🐏")

    assert "error" not in result
    assert result.get("user") == "不约儿童🐏🐏"
    assert driver.card_open is True


@pytest.mark.asyncio
async def test_seated_user_absent_from_the_online_list_reports_not_found():
    """在座但在线列表里翻到底确实没有：如实回报未找到，不得短路报座位号。"""
    manager, _driver = _wire(members=["Joyer", "Chainer"])
    _seat_user("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("不约儿童🐏🐏")

    assert result["error"] == "User not found in online users list"
    assert result["user"] == "不约儿童🐏🐏"
    assert "seat" not in result


@pytest.mark.asyncio
async def test_non_seated_user_still_uses_the_online_list():
    """不在座位上的用户也走同一条在线列表路径。"""
    manager, driver = _wire(members=["Joyer", "斯德哥尔摩情人"])
    _seat_user("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("斯德哥尔摩情人")

    assert "error" not in result
    assert driver.card_open is True


@pytest.mark.asyncio
async def test_canonical_name_is_resolved_to_the_visible_nickname_before_searching():
    """canonical 名（主账号）先解析成分身名，再拿分身名去抽屉里找人。

    两个命名域的字符串不同：拿 canonical 名直接和 UI 文本比永远不相等，于是会把明明
    在房间里的人报成「未找到」。调用方给哪个名字都不该由调用方决定。
    """
    seen = []

    async def resolver(username):
        seen.append(username)
        return {"forchain": "链子"}.get(username, username)

    manager, driver = _wire(
        members=[("链子", "密友"), "小红"], name_resolver=resolver
    )

    result = await manager.open_user_profile("forchain")

    assert "error" not in result
    # 回报里仍是调用方给的那个名字（既有行为），UI 上找人的是解析后的分身名。
    assert result["user"] == "forchain"
    assert seen == ["forchain"]
    assert driver.card_open is True


@pytest.mark.asyncio
async def test_visible_nickname_passes_through_resolution_unchanged():
    """已经在 UI 域里的名字不会被二次翻译。"""

    async def resolver(username):
        return {"forchain": "链子"}.get(username, username)

    manager, driver = _wire(members=["链子"], name_resolver=resolver)

    result = await manager.open_user_profile("链子")

    assert result["user"] == "链子"
    assert driver.card_open is True


@pytest.mark.asyncio
async def test_the_card_is_handed_over_to_the_caller_on_success():
    """成功时抽屉连同资料卡一起交给调用方。

    卡片与抽屉共用同一个 ivClose，会话在这里收尾就等于把刚交出去的卡片拆掉，
    于是送礼 / 房管这些「要在资料卡上继续操作」的调用方就无从下手了。
    """
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager, _ = _wire(driver)

    await manager.open_user_profile("小明")

    assert driver.drawer_open is True
    assert driver.card_open is True
    assert driver.close_calls == 0


@pytest.mark.asyncio
async def test_the_drawer_is_closed_when_the_card_never_opens():
    """点了行却没弹出卡片：回报原样的那句报错，并把抽屉收干净。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], card_fails=True)
    manager, _ = _wire(driver)

    result = await manager.open_user_profile("小明")

    assert result["error"] == "Failed to click user element"
    assert result["user"] == "小明"
    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_each_failure_keeps_its_own_wording():
    """三句报错在调用方面前是三句话，统一入口不能把它们合并。"""
    open_failed, _ = _wire(InMemoryOnlineDrawerDriver(members=["小明"], open_fails=True))
    assert (await open_failed.open_user_profile("小明")) == {
        "error": "Failed to open online users list",
        "user": "小明",
    }

    settle_failed, _ = _wire(InMemoryOnlineDrawerDriver(members=["小明"], settle_fails=True))
    assert (await settle_failed.open_user_profile("小明")) == {
        "error": "Failed to find online users container",
        "user": "小明",
    }

    missing, _ = _wire(InMemoryOnlineDrawerDriver(members=["小红"]))
    assert (await missing.open_user_profile("小明"))["error"] == (
        "User not found in online users list"
    )


@pytest.mark.asyncio
async def test_a_drawer_that_will_not_settle_is_never_left_open():
    """开了却没落定：这是本会话打开的抽屉，必须收掉，不能悬着。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], settle_fails=True)
    manager, _ = _wire(driver)

    await manager.open_user_profile("小明")

    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_the_online_list_is_allowed_to_settle_before_scrolling():
    """抽屉刚打开时列表还在首帧布局：必须先等稳定，否则首次下滑会被误判成边界。

    落定静默如今住在端口适配器里（见 `SETTLE_SECONDS`），这条断言读的是事件流顺序，
    而不是「谁调了哪个私有方法」。
    """
    journal = []
    driver = InMemoryOnlineDrawerDriver(
        members=["Joyer", "斯德哥尔摩情人"], page_size=1, journal=journal
    )
    manager, _ = _wire(driver)

    await manager.open_user_profile("斯德哥尔摩情人")

    assert "drawer:settle" in journal
    assert journal.index("drawer:settle") < journal.index("drawer:scroll")


@pytest.mark.asyncio
async def test_open_user_profile_delegates_to_the_online_list_entry_point():
    """`open_user_profile` 与 `open_user_profile_from_online_list` 是同一条路：
    两个入口都必须经由抽屉会话，绝不能有一个还留着裸 Appium。"""
    manager, _ = _wire(members=["小明", "小红"])

    via_list = await manager.open_user_profile_from_online_list("小红")
    via_alias = await manager.open_user_profile("小红")

    assert via_list == via_alias == {"user": "小红"}


@pytest.mark.asyncio
async def test_close_user_profile_dismisses_the_card_back_to_the_room():
    """交接的另一半：把悬着的卡片收回房间，不留下任何弹窗。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], journal=journal)
    manager, _ = _wire(driver)
    await manager.open_user_profile("小明")

    await manager.close_user_profile()

    assert driver.card_open is False
    assert driver.drawer_open is False
    assert "card:dismiss" in journal


@pytest.mark.asyncio
async def test_close_user_profile_does_nothing_when_no_card_is_out():
    """没有卡片悬着：不去关一个本来就没打开的抽屉，也不夺取归属。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager, _ = _wire(driver)

    await manager.close_user_profile()

    assert driver.close_calls == 0
    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_a_card_that_will_not_close_is_reported_but_not_faked():
    """关不掉卡片时保持原状并留下警告，绝不换成盲按返回把房间一起带走。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], dismiss_fails=True)
    manager, _ = _wire(driver)
    await manager.open_user_profile("小明")

    await manager.close_user_profile()

    assert driver.card_open is True, "收不掉就如实留着，不假装收拾干净了"


@pytest.mark.asyncio
async def test_lookup_never_emits_a_back_press_on_any_path():
    """找人的每一条路径（含各种失败）都不该出现一次盲按返回。"""
    for driver_kwargs in (
        {},
        {"open_fails": True},
        {"settle_fails": True},
        {"card_fails": True},
        {"close_fails": True},
    ):
        journal = []
        driver = InMemoryOnlineDrawerDriver(
            members=["小明"], journal=journal, **driver_kwargs
        )
        manager, _ = _wire(driver)

        await manager.open_user_profile("小明")
        await manager.close_user_profile()

        assert not any("back" in event for event in journal), (driver_kwargs, journal)


@pytest.mark.asyncio
async def test_handover_is_only_released_after_the_card_really_opened():
    """卡片没开出来就不能 release：交接只发生在成功路径上，失败路径照常收尾。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], card_fails=True)
    manager, _ = _wire(driver)

    result = await manager.open_user_profile("小明")

    assert result["error"] == "Failed to click user element"
    assert driver.close_calls == 1, "失败路径照常收尾"
