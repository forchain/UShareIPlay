"""房管流程全程走抽屉会话，**保证**确认框、资料卡与抽屉都收干净（#439 迁入 `OnlineDrawerManager`）。

被测的是 `AdminManager.manage_admin` 的编排：抽屉 -> 资料卡 -> 房管开关 -> 确认框 -> 收尾。
真实屏幕整块换成了 `tests/fakes/in_memory_online_drawer_driver.py`，因此这些断言与
Appium 时序无关。

最要紧的不是「房管能不能设上」，而是**每一条路径都收拾干净**：旧实现在「已经是房管」
「还不是房管」两条分支上用 `key_actions.press_back()` 收场，而盲按返回会误退出派对房间
（spec #426 问题陈述 #1）；剩下三条路径则靠散落各处的
`RecoveryManager.close_drawer('online_drawer')` 兜底，其中「找不到确认框」那条根本兜不到 ——
旧实现在那里直接 return，抽屉与资料卡留在屏幕上。现在三层都走页内手势，收不掉只记警告。
"""

import pytest

from ushareiplay.managers.admin_manager import AdminManager
from ushareiplay.managers.online_drawer import OnlineDrawerManager
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


class _Handler:
    """最小 handler：抽屉会话只用到 logger，controller 缺席即不加 UI 锁。"""

    def __init__(self):
        self.logger = None
        self.controller = None


@pytest.fixture(autouse=True)
def reset_singletons():
    AdminManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    yield
    AdminManager.reset_instance()
    OnlineDrawerManager.reset_instance()


def _wire(*, members=("小明",), name_resolver=None, **driver_kwargs):
    """装好抽屉会话与 `AdminManager`，把屏幕交给内存替身。"""
    # 单例只允许 initialize 一次（ADR-0009）：同一个测试里重装之前必须先 reset。
    AdminManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    driver = InMemoryOnlineDrawerDriver(members=list(members), **driver_kwargs)
    OnlineDrawerManager.initialize(
        handler=_Handler(), driver=driver, name_resolver=name_resolver
    )
    manager = AdminManager.initialize(_Handler())
    return manager, driver


# ---------------------------------------------------------------------------
# 找不到人 / 找不到控件：文案逐字不变，抽屉与资料卡照样收干净
# ---------------------------------------------------------------------------


async def test_user_not_in_the_drawer_reports_and_leaves_nothing_on_screen():
    """在线名单里没这个人：报旧实现的原话，抽屉由会话自己收掉。

    旧实现在这条路径上由 `open_user_profile` 收尾；现在会话自己收，行为一致，但不再
    需要外层去记得关。
    """
    journal = []
    manager, driver = _wire(members=["小红"], journal=journal)

    result = await manager.manage_admin(enable=True, target_nickname="小明")

    assert result == {"error": "User not found in online users list", "user": "小明"}
    assert driver.drawer_open is False
    assert driver.card_open is False
    assert not any("back" in event for event in journal), journal


async def test_profile_card_that_never_opens_reports_and_closes_the_drawer():
    """行点开了但资料卡没弹出来：报旧文案，抽屉照样收掉，不许把人留在抽屉里。"""
    journal = []
    manager, driver = _wire(members=["小明"], card_fails=True, journal=journal)

    result = await manager.manage_admin(enable=True, target_nickname="小明")

    assert result == {"error": "Failed to click user element", "user": "小明"}
    assert driver.drawer_open is False
    assert driver.card_open is False
    assert not any("back" in event for event in journal), journal


async def test_card_without_the_admin_button_reports_and_closes_the_card():
    """卡片上没有房管开关：报旧文案，先收卡片再连抽屉一起收。"""
    journal = []
    manager, driver = _wire(members=["小明"], admin_invite_label=None, journal=journal)

    result = await manager.manage_admin(enable=True, target_nickname="小明")

    assert result == {"error": "Failed to find manager invite button", "user": "小明"}
    assert driver.admin_invite_clicks == []
    assert "card:dismiss" in journal, "卡片还开着就必须收掉"
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


async def test_missing_confirm_button_reports_and_closes_every_layer():
    """点完开关却没有确认框：同样收干净，不留悬着的确认框与卡片。

    旧实现在这条路径上直接 return，资料卡与抽屉留在屏幕上 —— 悬着的抽屉下一次盲按返回
    就会退出派对房间。
    """
    journal = []
    manager, driver = _wire(
        members=["小明"], admin_steps_fails=("confirm",), journal=journal
    )

    result = await manager.manage_admin(enable=True, target_nickname="小明")

    assert result == {"error": "Failed to find Invited confirmation button", "user": "小明"}
    assert "admin:dismiss" in journal, "确认框还开着就必须先收它"
    assert journal.index("admin:confirm:fails") < journal.index("admin:dismiss")
    assert journal.index("admin:dismiss") < journal.index("card:dismiss")
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


async def test_a_confirm_box_that_will_not_close_is_logged_and_left_alone(caplog):
    """确认框的页内关闭键都点不到：记一条警告、保持原状，绝不盲按返回。

    屏幕上多一层弹窗只是难看一次；赌一次 `press_back` 可能是退出派对房间。走「确认框
    点不到」那条路，因为只有它会在收尾时还留着一个确认框。
    """
    import logging

    manager, driver = _wire(
        members=["小明"], admin_steps_fails=("confirm",), dismiss_admin_fails=True
    )

    with caplog.at_level(logging.WARNING):
        result = await manager.manage_admin(enable=True, target_nickname="小明")

    assert result == {"error": "Failed to find Invited confirmation button", "user": "小明"}, (
        "收不掉确认框不该改掉这次房管操作的结果"
    )
    assert driver.admin_confirm_pending is True
    assert any("未能通过页内关闭键收起房管确认框" in r.message for r in caplog.records)
    # 卡片与抽屉那一层还是收掉了：抽屉悬在屏幕上才是会被盲按返回带走的那一层。
    assert driver.card_open is False
    assert driver.drawer_open is False


# ---------------------------------------------------------------------------
# 盲按返回的禁令（spec #426 问题陈述 #1）
# ---------------------------------------------------------------------------


async def test_no_admin_path_ever_emits_a_back_press():
    """把房管的每条路径各走一遍，事件流里一次盲按返回都不该出现。

    旧实现在两条幂等分支上正是用 `key_actions.press_back()` 收场，而它们只收掉最上面
    那层确认框，底下的资料卡与抽屉照样悬着。
    """
    scenarios = [
        {},
        {"admin_invite_label": "解除管理"},
        {"admin_steps_fails": ("invite",)},
        {"admin_steps_fails": ("confirm",)},
        {"admin_invite_label": None},
        {"card_fails": True},
        {"members": ["小红"]},
        {"admin_steps_fails": ("confirm",), "dismiss_admin_fails": True},
        {"open_fails": True},
        {"close_fails": True},
    ]
    for index, kwargs in enumerate(scenarios):
        journal = []
        members = kwargs.pop("members", ["小明"])
        manager, driver = _wire(members=members, journal=journal, **kwargs)

        await manager.manage_admin(enable=True, target_nickname="小明")

        assert not any("back" in event for event in journal), (index, journal)


# ---------------------------------------------------------------------------
# 两个命名域：canonical 名 -> UI 可见昵称，由抽屉这一层解析
# ---------------------------------------------------------------------------


async def test_canonical_username_is_resolved_inside_the_drawer_flow():
    """canonical 名（主账号）进流程，抽屉里点到的是分身名那一行，登记也记分身名。

    解析发生在抽屉会话里而不是命令层：在线列表里只有屏幕上显示的名字能定位到人，两个
    命名域的字符串不同，拿 canonical 名直接比 UI 文本永远不相等。而麦位观测与 `:info`
    都是拿分身名比对的，所以本地房管名单也必须记分身名。
    """

    async def resolver(username):
        return {"forchain": "链子"}.get(username, username)

    journal = []
    manager, driver = _wire(
        members=["链子", "小红"], name_resolver=resolver, journal=journal
    )

    result = await manager.manage_admin(enable=True, target_nickname="forchain")

    assert result == {"user": "链子", "action": "Invited"}
    assert f"card:open:链子" in journal, "点开的是分身名那一行，而不是找不到人"
    assert manager.is_room_admin("链子")
    assert not manager.is_room_admin("forchain")
    assert driver.drawer_open is False


async def test_a_broken_name_resolver_does_not_break_the_admin_flow():
    """命名域解析器抛错：按原名继续找，与旧实现在这处的兜底一致。

    解析器是别处的单例，让它的一次抖动把整条房管流程变成硬失败并不划算。
    """

    async def resolver(username):
        raise RuntimeError("解析器抽风")

    journal = []
    manager, driver = _wire(members=["小明"], name_resolver=resolver, journal=journal)

    result = await manager.manage_admin(enable=True, target_nickname="小明")

    assert result == {"user": "小明", "action": "Invited"}
    assert "card:open:小明" in journal
    assert driver.drawer_open is False


# ---------------------------------------------------------------------------
# :admin 命令：薄适配器
# ---------------------------------------------------------------------------


class _RecordingAdminManager:
    """只记下命令交过来的东西：命令层不该替流程做命名域解析。"""

    def __init__(self):
        self.given = []

    async def manage_admin(self, enable, target_nickname):
        self.given.append((enable, target_nickname))
        return {"user": target_nickname, "action": "Invited" if enable else "Dismissed"}


@pytest.mark.parametrize(
    "content, parameters, expected",
    [
        (":admin 1 张三", ["1", "张三"], (True, "张三")),                  # 显式指定目标
        (":admin  0  张三 ", ["0", " 张三 "], (False, "张三")),            # 参数两侧空白照旧裁掉
        (":admin 1", ["1"], (True, "群主")),                               # 给了开关没给人：操作自己
        (":admin 0   ", ["0", "   "], (False, "群主")),                    # 空白参数等同于未指定
        (':admin 1 "张三 王五"', ["1", '"张三 王五"'], (True, "张三 王五")),  # 引号里的空格仍属同一个名字
    ],
)
async def test_admin_command_parses_the_target_and_delegates_verbatim(
    content, parameters, expected
):
    """参数解析不变，且命令层把拿到的名字**原样**交下去。"""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from ushareiplay.commands.admin import AdminCommand
    from ushareiplay.models.message_info import MessageInfo

    fake_manager = _RecordingAdminManager()
    controller = SimpleNamespace(soul_handler=MagicMock(), music_handler=MagicMock())
    command = AdminCommand(controller)

    with patch(
        "ushareiplay.commands.admin.AdminManager.instance", return_value=fake_manager
    ):
        result = await command.do_process(
            MessageInfo(content=content, nickname="群主"), parameters
        )

    assert fake_manager.given == [expected]
    assert result == {"user": expected[1], "action": "Invited" if expected[0] else "Dismissed"}


@pytest.mark.parametrize(
    "content, parameters, message",
    [
        (":admin", [], "Missing parameter. Use: :admin [1|0] [昵称]"),
        (":admin 歪 张三", ["歪", "张三"], "Invalid parameter. Use: :admin [1|0] [昵称]"),
        (':admin 1 "张三', ['"张三'], "Invalid parameters format. Please check quotes."),
    ],
)
async def test_admin_command_parameter_errors_keep_their_legacy_wording(
    content, parameters, message
):
    """三条参数报错逐字保留：它们直接进聊天气泡，迁移不是重写。

    这三条都在进流程之前返回，因此不需要装任何单例 —— 命令层不再在构造期查单例。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from ushareiplay.commands.admin import AdminCommand
    from ushareiplay.models.message_info import MessageInfo

    controller = SimpleNamespace(soul_handler=MagicMock(), music_handler=MagicMock())
    command = AdminCommand(controller)

    result = await command.do_process(MessageInfo(content=content, nickname="群主"), parameters)

    assert result == {"error": message, "user": "群主"}


async def test_admin_command_does_not_resolve_the_nickname_itself():
    """回归防线：命令层不触碰命名域解析器。

    解析只在抽屉会话里发生一次；命令层若再解析，canonical 名会在命令层就被翻成分身名，
    而下游按 canonical 名查库的那些路径就会失配。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from ushareiplay.commands.admin import AdminCommand
    from ushareiplay.models.message_info import MessageInfo

    fake_manager = _RecordingAdminManager()
    controller = SimpleNamespace(soul_handler=MagicMock(), music_handler=MagicMock())
    command = AdminCommand(controller)

    with patch(
        "ushareiplay.commands.admin.AdminManager.instance", return_value=fake_manager
    ), patch.object(
        type(command),
        "info_manager",
        new=property(lambda _self: (_ for _ in ()).throw(AssertionError("命令层不该解析昵称"))),
    ):
        result = await command.do_process(
            MessageInfo(content=":admin 1 forchain", nickname="群主"), ["1", "forchain"]
        )

    assert fake_manager.given == [(True, "forchain")], "canonical 名原样交给流程"
    assert result == {"user": "forchain", "action": "Invited"}
