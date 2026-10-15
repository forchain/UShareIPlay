"""私聊发送全程走抽屉会话，**保证**回到房间（#435 迁入 `OnlineDrawerManager`）。

被测的是 `UserManager.send_private_message_to_user` 的编排：抽屉 -> 资料卡 -> 头像 ->
私聊页 -> 输入 -> 发送 -> 回房间。真实屏幕整块换成了
`tests/fakes/in_memory_online_drawer_driver.py`，因此这些断言与 Appium 时序无关。

最要紧的不是「能不能发出去」，而是**每一条失败路径都回到房间**：旧实现在失败时直接
`return False`，把资料卡或私聊页悬在屏幕上，而下一次盲按返回就会把它们连同派对房间
一起带走（spec #426 问题陈述 #1）。
"""

import pytest

from ushareiplay.managers.online_drawer import OnlineDrawerManager
from ushareiplay.managers.user_manager import UserManager
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


class _Handler:
    """最小 handler：抽屉会话只用到 logger；切回前台的 `key_actions` 记一下。"""

    def __init__(self):
        self.logger = None
        self.switched_to_app = 0

        class _KeyActions:
            def __init__(self, owner):
                self._owner = owner

            def switch_to_app(self):
                self._owner.switched_to_app += 1

        self.key_actions = _KeyActions(self)


@pytest.fixture(autouse=True)
def reset_singletons():
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    yield
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()


def _wire(*, members=("小明",), name_resolver=None, **driver_kwargs):
    """装好抽屉会话与 `UserManager`，把屏幕交给内存替身。"""
    driver = InMemoryOnlineDrawerDriver(members=list(members), **driver_kwargs)
    # 单例只允许 initialize 一次（ADR-0009）：同一个测试里重装之前必须先 reset。
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    OnlineDrawerManager.initialize(
        handler=_Handler(), driver=driver, name_resolver=name_resolver
    )
    handler = _Handler()
    manager = UserManager.initialize(handler)
    return manager, driver, handler


@pytest.mark.asyncio
async def test_private_message_walks_drawer_card_home_chat_and_returns():
    """完整链路一次走通：抽屉 -> 资料卡 -> 主页 -> 私聊页 -> 输入 -> 发送 -> 回房间。"""
    journal = []
    manager, driver, handler = _wire(members=["Alice"], journal=journal)

    ok = await manager.send_private_message_to_user("Alice", "hello")

    assert ok is True
    assert handler.switched_to_app == 1, "私聊前先把 App 切回前台"
    assert driver.typed_messages == ["hello"]
    assert driver.room_returns == ["private_room_entry"]
    assert journal.index("card:open:Alice") < journal.index("chat:home")
    assert journal.index("chat:home") < journal.index("chat:chat_page")
    assert journal.index("chat:chat_page") < journal.index("chat:type")
    assert journal.index("chat:type") < journal.index("chat:submit")
    assert journal[-1].startswith("room:return")
    # 走完之后屏幕上什么都不该剩：既没有抽屉，也没有悬着的卡片。
    assert driver.drawer_open is False
    assert driver.card_open is False


@pytest.mark.asyncio
async def test_private_message_resolves_the_canonical_name_before_navigating():
    """canonical 名先解析成分身名，再去抽屉里点开那一张卡片。"""
    seen = []
    journal = []

    async def resolver(username):
        seen.append(username)
        return {"forchain": "链子"}.get(username, username)

    manager, driver, _handler = _wire(
        members=["链子", "小红"], name_resolver=resolver, journal=journal
    )

    ok = await manager.send_private_message_to_user("forchain", "hi")

    assert ok is True
    assert seen == ["forchain"]
    # 点开的是解析后的分身名那张卡片，不是 canonical 名。
    assert "card:open:链子" in journal
    assert not any("forchain" in event for event in journal), journal
    assert driver.chat_reached == "submit"


@pytest.mark.asyncio
async def test_private_message_returns_false_when_the_user_is_absent():
    """人不在在线列表里：不进卡片，但**已经回到房间**（会话收尾）。"""
    manager, driver, _handler = _wire(members=["Joyer"])

    ok = await manager.send_private_message_to_user("查无此人", "hey")

    assert ok is False
    assert driver.card_open is False
    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_private_message_returns_false_when_the_drawer_will_not_open():
    """抽屉打不开：如实 False，抽屉本就没开着，没什么要收的。"""
    manager, driver, _handler = _wire(open_fails=True)

    ok = await manager.send_private_message_to_user("小明", "hey")

    assert ok is False
    assert driver.close_calls == 0
    assert driver.card_open is False


@pytest.mark.asyncio
async def test_private_message_returns_false_when_the_card_never_opens():
    """点了行却没弹出卡片：不往下走，把抽屉收干净。"""
    manager, driver, _handler = _wire(card_fails=True)

    ok = await manager.send_private_message_to_user("小明", "hey")

    assert ok is False
    assert driver.chat_reached is None
    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_private_message_returns_false_when_the_drawer_will_not_settle():
    """开了却没落定：本会话打开的抽屉必须收掉。"""
    manager, driver, _handler = _wire(settle_fails=True)

    ok = await manager.send_private_message_to_user("小明", "hey")

    assert ok is False
    assert driver.drawer_open is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_step", ["home", "chat_page", "type", "submit"])
async def test_every_failing_step_still_returns_to_the_room(failing_step):
    """导航上的任何一步失败，都要回到房间。

    这是本文件最要紧的一条：失败路径直接 `return False` 会把资料卡或私聊页悬在屏幕上，
    而下一次盲按返回就会把它们连同派对房间一起带走。
    """
    manager, driver, _handler = _wire(chat_steps_fails=(failing_step,))

    ok = await manager.send_private_message_to_user("小明", "hey")

    assert ok is False
    assert driver.room_returns == ["private_room_entry"], "失败了也必须回房间"
    assert driver.card_open is False
    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_a_message_sent_but_not_returned_counts_as_failed():
    """发出去了却回不去房间：这次私聊按失败算（与旧实现一致），并记一条警告。"""
    manager, driver, _handler = _wire(room_return_fails=True)

    ok = await manager.send_private_message_to_user("小明", "hey")

    assert ok is False
    assert driver.chat_reached == "submit", "消息确实发出去了"


@pytest.mark.asyncio
async def test_returning_through_a_fallback_entry_still_counts_as_success():
    """落到兜底入口（房间悬浮入口 / 主页左上角返回）也算回到房间了。

    具体命中哪个入口是适配器的事（见 `ROOM_ENTRY_KEYS`），这里断言的是「换个入口也
    一样算数」。
    """
    manager, driver, _handler = _wire(room_entry_key="item_left_back")

    ok = await manager.send_private_message_to_user("小明", "hey")

    assert ok is True
    assert driver.room_returns == ["item_left_back"]


@pytest.mark.asyncio
async def test_private_message_never_presses_back_on_any_path():
    """整条私聊链路（含每一种失败）都不该出现一次盲按返回。"""
    for driver_kwargs in (
        {},
        {"open_fails": True},
        {"settle_fails": True},
        {"card_fails": True},
        {"chat_steps_fails": ("home",)},
        {"chat_steps_fails": ("submit",)},
        {"room_return_fails": True},
    ):
        journal = []
        manager, driver, _handler = _wire(journal=journal, **driver_kwargs)

        await manager.send_private_message_to_user("小明", "hey")

        assert not any("back" in event for event in journal), (driver_kwargs, journal)
        # 卡片要么已经收掉，要么回房间这一步确实被走了一遍（只是报告了失败）。
        assert driver.card_open is False or "room:return:fails" in journal, driver_kwargs


@pytest.mark.asyncio
async def test_a_card_that_survives_a_failed_chat_can_still_be_swept_up():
    """回房间失败之后卡片可能还悬着：调用方仍可以用 `close_user_profile` 兜底收场。"""
    manager, driver, _handler = _wire(room_return_fails=True, chat_steps_fails=("home",))

    ok = await manager.send_private_message_to_user("小明", "hey")

    assert ok is False
    assert driver.room_returns == [], "回房间这一步失败了"
    assert driver.card_open is True, "卡片还悬在屏幕上"

    await manager.close_user_profile()

    assert driver.card_open is False
    assert driver.drawer_open is False
