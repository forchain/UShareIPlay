"""送礼流程全程走抽屉会话，**保证**弹窗与抽屉都收干净（#438 迁入 `OnlineDrawerManager`）。

被测的是 `UserManager.send_gift` 的编排：抽屉 -> 资料卡 -> 送礼弹窗 ->（小黄鸭即时送
或 赠送/使用 + 确认）-> 收尾。真实屏幕整块换成了
`tests/fakes/in_memory_online_drawer_driver.py`，因此这些断言与 Appium 时序无关。

最要紧的不是「能不能送出去」，而是**每一条路径都收拾干净**：旧实现在两条失败路径上
用 `key_actions.press_back()` 收弹窗，把资料卡与抽屉悬在屏幕上，而下一次盲按返回就会
把它们连同派对房间一起带走（spec #426 问题陈述 #1）。这里两层弹窗都用页内手势收，
收不掉就只记警告，绝不盲按返回。
"""

import pytest

from ushareiplay.managers.online_drawer import OnlineDrawerManager
from ushareiplay.managers.user_manager import UserManager
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


class _Handler:
    """最小 handler：抽屉会话只用到 logger。"""

    def __init__(self):
        self.logger = None


@pytest.fixture(autouse=True)
def reset_singletons():
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    yield
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()


def _wire(*, members=("小明",), name_resolver=None, **driver_kwargs):
    """装好抽屉会话与 `UserManager`，把屏幕交给内存替身。"""
    # 单例只允许 initialize 一次（ADR-0009）：同一个测试里重装之前必须先 reset。
    UserManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    driver = InMemoryOnlineDrawerDriver(members=list(members), **driver_kwargs)
    OnlineDrawerManager.initialize(
        handler=_Handler(), driver=driver, name_resolver=name_resolver
    )
    manager = UserManager.initialize(_Handler())
    return manager, driver


# ---------------------------------------------------------------------------
# 送礼入口
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_gift_entry_reports_and_still_closes_the_card_and_drawer():
    """资料卡上没有「送礼物」入口：报旧实现的原话，并把卡片连同抽屉收干净。

    旧实现在这里直接 return，抽屉与资料卡一起悬在屏幕上 —— 那正是下一次盲按返回会
    退出派对房间的状态（spec #426 问题陈述 #1）。
    """
    manager, driver = _wire(members=["小明"], gift_steps_fails=("entry",))

    result = await manager.send_gift("小明")

    assert result == {'error': '未找到送礼物入口'}
    assert driver.card_open is False
    assert driver.drawer_open is False


# ---------------------------------------------------------------------------
# 小黄鸭：背包为空时的兜底礼物，点一下即送
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yellow_duck_is_sent_by_tapping_it_and_needs_no_give_button():
    """小黄鸭点一下即送出：不点「赠送」，也不等确认框。

    旧实现靠 `luck_item` 的文案判断走哪条路，而那份文案带件数（`小黄鸭x3`），所以
    聊天里报的是 `小黄鸭 送你啦` 而不是 `小黄鸭x3 送你啦`。
    """
    journal = []
    manager, driver = _wire(
        members=["小明"], gift_name="小黄鸭x3", gift_soul_power="+12灵魂力", journal=journal
    )

    result = await manager.send_gift("小明")

    assert result == {'success': '小黄鸭 送你啦'}
    assert driver.gift_item_clicks == ["小黄鸭x3"]
    assert driver.gift_action_clicks == [], "即时送出不该再点赠送/使用"
    assert driver.confirm_pending is False
    assert driver.gift_popup_open is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    # 顺序：先点送礼物入口，再点小黄鸭，弹窗自己走掉之后才轮到收卡片。
    assert journal.index("gift:entry") < journal.index("gift:click:item")
    assert journal.index("gift:click:item") < journal.index("card:dismiss")
    assert not any("back" in event for event in journal), journal


# ---------------------------------------------------------------------------
# 商店礼物与背包道具：两个互斥的动作按钮
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_gift_clicks_give_and_never_waits_for_a_confirm_box():
    """商店礼物点「赠送」就送出去了：没有确认框，也不该去等一个不存在的确认框。"""
    journal = []
    manager, driver = _wire(
        members=["小明"],
        gift_action_key="give_gift",
        gift_name="高级福袋x2",
        gift_soul_power="+12灵魂力",
        journal=journal,
    )

    result = await manager.send_gift("小明")

    assert result == {'success': '高级福袋 送你啦'}
    assert driver.gift_action_clicks == ["give_gift"]
    assert driver.gift_item_clicks == [], "商店礼物不该点礼物本身"
    assert "gift:confirm" not in journal
    assert driver.gift_popup_open is False
    assert driver.card_open is False
    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_backpack_item_clicks_use_then_confirms_the_second_dialog():
    """背包道具点「使用」之后还有一道确认框，两步都要走，顺序不能颠倒。"""
    journal = []
    manager, driver = _wire(
        members=["小明"],
        gift_action_key="use_item",
        gift_name="初级福袋x1",
        journal=journal,
    )

    result = await manager.send_gift("小明")

    assert result == {'success': '初级福袋 送你啦'}
    assert driver.gift_action_clicks == ["use_item"]
    assert journal.index("gift:click:action:use_item") < journal.index("gift:confirm")
    assert journal.index("gift:confirm") < journal.index("card:dismiss")
    assert driver.gift_popup_open is False
    assert driver.card_open is False
    assert driver.drawer_open is False


# ---------------------------------------------------------------------------
# 失败路径：文案逐字不变，收尾从「盲按返回」换成「分层收干净」
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gift_popup_that_never_appears_reports_the_legacy_wording_and_cleans_up():
    """点了送礼物但弹窗没起来：报旧文案，然后把弹窗与卡片一起收掉。

    旧实现在这条路径上直接 return，抽屉与资料卡留在屏幕上 —— 悬着的抽屉下一次盲按
    返回就会退出派对房间（spec #426 问题陈述 #1）。
    """
    manager, driver = _wire(members=["小明"], gift_steps_fails=("popup",))

    result = await manager.send_gift("小明")

    assert result == {'error': '送礼界面未出现'}
    assert driver.gift_popup_open is False
    assert driver.card_open is False
    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_missing_gift_item_reports_and_closes_the_popup_that_stays_out():
    """弹窗里读不到选中礼物：旧实现在这里 `press_back`，现在必须收干净再走。

    这两条 `press_back`（读不到礼物、读不到确认框）是 spec #426 点名的退房来源：
    它们收掉的是最上面那层弹窗，底下的资料卡与抽屉照样悬着。
    """
    journal = []
    manager, driver = _wire(
        members=["小明"], gift_action_key="use_item", gift_steps_fails=("item",), journal=journal
    )

    result = await manager.send_gift("小明")

    assert result == {'error': 'Failed to find gift'}
    assert "gift:dismiss" in journal, "弹窗还在就必须先收弹窗"
    assert journal.index("gift:dismiss") < journal.index("card:dismiss")
    assert driver.gift_popup_open is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_missing_confirm_button_reports_and_closes_every_layer():
    """点完「使用」却没有确认框：同样收干净，不留悬着的弹窗与卡片。"""
    journal = []
    manager, driver = _wire(
        members=["小明"],
        gift_action_key="use_item",
        gift_name="初级福袋x1",
        gift_steps_fails=("confirm",),
        journal=journal,
    )

    result = await manager.send_gift("小明")

    assert result == {'error': '未找到确认使用按钮'}
    assert journal.index("gift:confirm:fails") < journal.index("gift:dismiss")
    assert journal.index("gift:dismiss") < journal.index("card:dismiss")
    assert driver.gift_popup_open is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_a_gift_popup_that_will_not_close_is_logged_and_left_alone(caplog):
    """弹窗的页内关闭键都点不到：记一条警告、保持原状，绝不盲按返回。

    屏幕上多一层弹窗只是难看一次；赌一次 `press_back` 可能是退出派对房间。
    走「确认框点不到」那条路，因为只有它会在收尾时还留着一个弹窗。
    """
    import logging

    manager, driver = _wire(
        members=["小明"],
        gift_action_key="use_item",
        gift_name="初级福袋x1",
        gift_steps_fails=("confirm",),
        dismiss_gift_fails=True,
    )

    with caplog.at_level(logging.WARNING):
        result = await manager.send_gift("小明")

    assert result == {'error': '未找到确认使用按钮'}, "收不掉弹窗不该改掉这次送礼的结果"
    assert driver.gift_popup_open is True
    assert any("未能通过页内关闭键收起送礼弹窗" in r.message for r in caplog.records)
    # 卡片与抽屉那一层还是收掉了：抽屉悬在屏幕上才是会被盲按返回带走的那一层。
    assert driver.card_open is False
    assert driver.drawer_open is False


@pytest.mark.asyncio
async def test_no_gift_step_ever_emits_a_back_press():
    """把送礼的每条路径各走一遍，事件流里一次盲按返回都不该出现。"""
    import pytest as _pytest

    scenarios = [
        {},
        {"gift_name": "小黄鸭x3"},
        {"gift_action_key": "use_item", "gift_name": "初级福袋x1"},
        {"gift_steps_fails": ("entry",)},
        {"gift_steps_fails": ("popup",)},
        {"gift_steps_fails": ("item",)},
        {"gift_steps_fails": ("confirm",), "gift_action_key": "use_item"},
        {"gift_steps_fails": ("action",)},
        {"dismiss_gift_fails": True},
    ]
    for index, kwargs in enumerate(scenarios):
        journal = []
        manager, driver = _wire(
            members=["小明"],
            gift_name=kwargs.pop("gift_name", "高级福袋x2"),
            journal=journal,
            **kwargs,
        )

        await manager.send_gift("小明")

        assert not any("back" in event for event in journal), (index, journal)


# ---------------------------------------------------------------------------
# 两个命名域：canonical 名 -> UI 可见昵称，由抽屉这一层解析
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canonical_username_is_resolved_inside_the_drawer_flow():
    """canonical 名（主账号）进流程，抽屉里点到的是分身名那一行。

    解析发生在抽屉会话里而不是命令层：在线列表里只有屏幕上显示的名字能定位到人，
    两个命名域的字符串不同，拿 canonical 名直接比 UI 文本永远不相等。
    """
    async def resolver(username):
        return {"forchain": "链子"}.get(username, username)

    manager, driver = _wire(
        members=["链子", "小红"], name_resolver=resolver, gift_name="小黄鸭x1"
    )

    result = await manager.send_gift("forchain")

    assert result == {'success': '小黄鸭 送你啦'}
    assert driver.gift_item_clicks == ["小黄鸭x1"]
    assert driver.drawer_open is False


# ---------------------------------------------------------------------------
# :gift 命令：薄适配器
# ---------------------------------------------------------------------------


class _RecordingUserManager:
    """只记下命令交过来的名字：命令层不该再替流程做命名域解析。"""

    def __init__(self):
        self.given = []

    async def send_gift(self, nickname):
        self.given.append(nickname)
        return {'success': f'{nickname} 送你啦'}


@pytest.mark.parametrize(
    "content, parameters, expected",
    [
        (":gift 张三", ["张三"], "张三"),                 # 显式指定目标
        (":gift  张三 ", [" 张三 "], "张三"),            # 参数两侧空白照旧裁掉
        (":gift", [], "群主"),                            # 未指定就送给自己
        (":gift    ", ["   "], "群主"),                  # 空白参数等同于未指定
    ],
)
async def test_gift_command_parses_the_target_and_delegates_verbatim(
    content, parameters, expected
):
    """参数解析不变，且命令层把拿到的名字**原样**交下去。

    #438 之前命令层会先 `resolve_visible_username` 一次；解析已经由抽屉会话内置完成，
    这里再解析一次等于让「解析不到时保留原名」这种兜底在两处各活一份。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from ushareiplay.commands.gift import GiftCommand
    from ushareiplay.models.message_info import MessageInfo

    fake_user_manager = _RecordingUserManager()
    controller = SimpleNamespace(soul_handler=MagicMock(), music_handler=MagicMock())
    command = GiftCommand(controller)

    with patch(
        "ushareiplay.commands.gift.UserManager.instance", return_value=fake_user_manager
    ):
        result = await command.do_process(
            MessageInfo(content=content, nickname="群主"), parameters
        )

    assert fake_user_manager.given == [expected]
    assert result == {'success': f'{expected} 送你啦'}


async def test_gift_command_does_not_resolve_the_nickname_itself():
    """回归防线：命令层不再触碰命名域解析器。

    解析只在抽屉会话里发生一次；命令层若再解析，canonical 名会在命令层就被翻成
    分身名，而下游按 canonical 名查库的那些路径就会失配。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from ushareiplay.commands.gift import GiftCommand
    from ushareiplay.models.message_info import MessageInfo

    fake_user_manager = _RecordingUserManager()
    controller = SimpleNamespace(soul_handler=MagicMock(), music_handler=MagicMock())
    command = GiftCommand(controller)

    with patch(
        "ushareiplay.commands.gift.UserManager.instance", return_value=fake_user_manager
    ), patch.object(
        type(command),
        "info_manager",
        new=property(lambda _self: (_ for _ in ()).throw(AssertionError("命令层不该解析昵称"))),
    ):
        result = await command.do_process(
            MessageInfo(content=":gift forchain", nickname="群主"), ["forchain"]
        )

    assert fake_user_manager.given == ["forchain"], "canonical 名原样交给流程"
    assert result == {'success': 'forchain 送你啦'}
