"""Manage-admin 用例与房管领域规则的离线测试（#550）。

被测的是「房管名单」与「授予/解除」的规则接缝：ADR-0008 的房主/管理员层级在这一层
落成命名异常（`AlreadyRoomAdmin` / `NotRoomAdmin` / `OperatorProtected`），而不是
聊天命令里的一句字符串。屏幕整块换成 `InMemoryOnlineDrawerDriver`，因此这里不碰
任何 Appium 时序。
"""

from types import SimpleNamespace

import pytest

from ushareiplay.adapters.inbound.chat.admin import (
    OPERATOR_PROTECTED_ERROR,
    AdminCommand,
)
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.modules.room.domain import (
    AlreadyRoomAdmin,
    NotRoomAdmin,
    OperatorProtected,
    RoomAdmins,
)
from ushareiplay.modules.room.use_cases import ManageAdmin, OnlineDrawer
from ushareiplay.modules.shared.roles import RolePolicy
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


def _drawer(driver, *, name_resolver=None):
    return OnlineDrawer(
        drawer=driver, name_resolver=name_resolver, ui_session=None
    )


def _wire(*, members=("Alice",), driver_kwargs=None, policy=None):
    driver = InMemoryOnlineDrawerDriver(members=list(members), **(driver_kwargs or {}))
    admins = RoomAdmins()
    manager = ManageAdmin(
        drawer=_drawer(driver),
        admins=admins,
        policy=policy or RolePolicy({}),
    )
    return manager, admins, driver


def test_room_admins_registry_reads_back_a_copy():
    admins = RoomAdmins()
    admins.add("Alice")
    admins.add("")
    assert admins.is_admin("Alice") is True
    assert admins.is_admin("Bob") is False
    assert admins.is_admin("") is False

    snapshot = admins.all()
    snapshot.add("Bob")
    assert admins.all() == {"Alice"}

    admins.remove("Alice")
    assert admins.all() == set()


async def test_invite_registers_the_visible_name():
    manager, admins, _driver = _wire()

    result = await manager.manage_admin(enable=True, target_nickname="Alice")

    assert result == {"user": "Alice", "action": "Invited"}
    assert admins.is_admin("Alice") is True


async def test_inviting_an_existing_admin_raises_the_named_domain_error():
    """屏幕已经是房管：不再多点一次，并抛出命名异常而不是返回裸 dict。"""
    manager, admins, driver = _wire(driver_kwargs={"admin_invite_label": "解除管理"})

    with pytest.raises(AlreadyRoomAdmin) as raised:
        await manager.manage_admin(enable=True, target_nickname="Alice")

    assert raised.value.user == "Alice"
    assert admins.is_admin("Alice") is True
    assert driver.admin_invite_clicks == []
    assert driver.drawer_open is False


async def test_dismissing_a_non_admin_raises_the_named_domain_error():
    manager, admins, driver = _wire()
    admins.add("Alice")

    with pytest.raises(NotRoomAdmin) as raised:
        await manager.manage_admin(enable=False, target_nickname="Alice")

    assert raised.value.user == "Alice"
    assert admins.is_admin("Alice") is False
    assert driver.admin_invite_clicks == []
    assert driver.drawer_open is False


async def test_the_room_owner_cannot_be_dismissed_and_the_drawer_is_not_opened():
    """ADR-0008 的 operator protection：房主是受保护的，失败在进 UI 之前。"""
    manager, _admins, driver = _wire()
    policy = RolePolicy({"soul": {"room_owner": "Owner"}})

    manager = ManageAdmin(
        drawer=_drawer(driver), admins=RoomAdmins(), policy=policy
    )

    with pytest.raises(OperatorProtected) as raised:
        await manager.manage_admin(
            enable=False, target_nickname="Owner", caller="SomeoneElse"
        )

    assert raised.value.user == "Owner"
    assert driver.open_calls == 0


async def test_only_the_owner_may_dismiss_a_configured_admin():
    """Owner > Admin：管理员不能解除另一个管理员，房主可以。"""
    policy = RolePolicy({"soul": {"room_owner": "Owner", "admin_users": ["Admin"]}})
    manager, admins, _driver = _wire(
        members=["Admin"],
        driver_kwargs={"admin_invite_label": "解除管理"},
        policy=policy,
    )
    admins.add("Admin")

    with pytest.raises(OperatorProtected):
        await manager.manage_admin(
            enable=False, target_nickname="Admin", caller="AnotherAdmin"
        )

    result = await manager.manage_admin(
        enable=False, target_nickname="Admin", caller="Owner"
    )

    assert result == {"user": "Admin", "action": "Dismissed"}
    assert admins.is_admin("Admin") is False


def _controller(driver, *, admins=None, policy=None):
    drawer = _drawer(driver)
    manager = ManageAdmin(
        drawer=drawer, admins=admins or RoomAdmins(), policy=policy or RolePolicy({})
    )
    return SimpleNamespace(
        soul_handler=SimpleNamespace(logger=None, log_error=lambda _m: None),
        music_handler=None,
        manage_admin=manager,
    )


@pytest.mark.parametrize(
    "content, parameters, expected",
    [
        (":admin 1 张三", ["1", "张三"], (True, "张三")),
        (":admin  0  张三 ", ["0", " 张三 "], (False, "张三")),
        (":admin 1", ["1"], (True, "群主")),
        (':admin 1 "张三 王五"', ["1", '"张三 王五"'], (True, "张三 王五")),
    ],
)
async def test_admin_command_parses_and_delegates_verbatim(content, parameters, expected):
    seen = []

    class _Recording:
        async def manage_admin(self, enable, target, caller=None):
            seen.append((enable, target, caller))
            return {"user": target, "action": "Invited"}

    controller = _controller(InMemoryOnlineDrawerDriver())
    controller.manage_admin = _Recording()
    command = AdminCommand(controller)

    result = await command.do_process(
        MessageInfo(content=content, nickname="群主"), parameters
    )

    assert seen == [(*expected, "群主")]
    assert result == {"user": expected[1], "action": "Invited"}


async def test_admin_command_translates_the_domain_errors_to_the_legacy_replies():
    driver = InMemoryOnlineDrawerDriver(members=["Alice"], admin_invite_label="解除管理")
    controller = _controller(driver)
    command = AdminCommand(controller)

    already = await command.do_process(
        MessageInfo(content=":admin 1 Alice", nickname="群主"), ["1", "Alice"]
    )
    assert already == {"error": "你已经是管理员了", "user": "Alice"}

    not_yet_driver = InMemoryOnlineDrawerDriver(members=["Alice"])
    not_yet = await AdminCommand(_controller(not_yet_driver)).do_process(
        MessageInfo(content=":admin 0 Alice", nickname="群主"), ["0", "Alice"]
    )
    assert not_yet == {"error": "你还不是管理员", "user": "Alice"}

    other_driver = InMemoryOnlineDrawerDriver(members=["Alice"])
    other_controller = _controller(other_driver)
    other_controller.manage_admin = ManageAdmin(
        drawer=_drawer(other_driver),
        admins=RoomAdmins(),
        policy=RolePolicy({"soul": {"room_owner": "Alice"}}),
    )
    protected = await AdminCommand(other_controller).do_process(
        MessageInfo(content=":admin 0 Alice", nickname="群主"), ["0", "Alice"]
    )
    assert protected == {"error": OPERATOR_PROTECTED_ERROR, "user": "Alice"}


@pytest.mark.parametrize(
    "parameters, message",
    [
        ([], "Missing parameter. Use: :admin [1|0] [昵称]"),
        (["歪", "张三"], "Invalid parameter. Use: :admin [1|0] [昵称]"),
        (['"张三'], "Invalid parameters format. Please check quotes."),
    ],
)
async def test_admin_command_parameter_errors_keep_their_wording(parameters, message):
    command = AdminCommand(_controller(InMemoryOnlineDrawerDriver()))

    result = await command.do_process(
        MessageInfo(content=":admin", nickname="群主"), parameters
    )

    assert result == {"error": message, "user": "群主"}
