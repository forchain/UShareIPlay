"""房管名单与 manage-admin 用例的角色隔离与记录行为（#550）。

原来的 `AdminManager` 拆成三块：`RoomAdmins` 领域对象、`ManageAdmin` 用例、
`adapters/inbound/chat/admin.py` 薄适配器。断言保留原有的对外行为：CRUD 返回副本、
RolePolicy 与房间房管名单互不自动推导、以及 :admin 命令只解析参数。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ushareiplay.adapters.inbound.chat.admin import AdminCommand
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.modules.room.domain import RoomAdmins
from ushareiplay.modules.room.use_cases import ManageAdmin, OnlineDrawer
from ushareiplay.modules.shared.roles import RolePolicy
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


class _Handler:
    """最小 handler：抽屉会话只用到 logger，controller 缺席即不加 UI 锁。"""

    def __init__(self):
        self.logger = None
        self.controller = None


def _wire(*, members=("Alice",), name_resolver=None, admin_invite_label="管理邀请", **driver_kwargs):
    """装好抽屉用例与 manage-admin，把真实屏幕交给内存替身。"""
    driver = InMemoryOnlineDrawerDriver(
        members=list(members), admin_invite_label=admin_invite_label, **driver_kwargs
    )
    admins = RoomAdmins()
    manager = ManageAdmin(
        drawer=OnlineDrawer(drawer=driver, name_resolver=name_resolver),
        admins=admins,
        policy=RolePolicy({}),
    )
    return manager, admins, driver


def test_room_admin_crud_returns_a_safe_copy():
    admins = RoomAdmins()
    assert admins.all() == set()
    assert not admins.is_admin("Alice")

    admins.add("Alice")
    assert admins.is_admin("Alice")
    assert admins.all() == {"Alice"}
    # Safe copy returned
    snapshot = admins.all()
    snapshot.add("Bob")
    assert admins.all() == {"Alice"}

    admins.add("Bob")
    assert admins.is_admin("Bob")
    assert admins.all() == {"Alice", "Bob"}

    admins.remove("Alice")
    assert not admins.is_admin("Alice")
    assert admins.all() == {"Bob"}

    # Removing non-existent user should not error
    admins.remove("NonExistent")
    assert admins.all() == {"Bob"}

    admins.clear()
    assert admins.all() == set()


def test_room_admin_decoupled_from_role_policy():
    admins = RoomAdmins()
    config = {
        "soul": {
            "owner": "OwnerUser",
            "admins": ["ConfigAdmin1", "ConfigAdmin2"],
        }
    }
    policy = RolePolicy(config)
    assert policy.is_admin("ConfigAdmin1")
    # RolePolicy admin is not automatically in the room-admin registry
    assert not admins.is_admin("ConfigAdmin1")

    admins.add("RoomOnlyAdmin")
    assert admins.is_admin("RoomOnlyAdmin")
    assert not policy.is_admin("RoomOnlyAdmin")


@pytest.mark.asyncio
async def test_manage_admin_invite_success():
    """邀请房管成功：点一次开关、点一次确认，记上房管名单，三层都收干净。"""
    journal = []
    manager, admins, driver = _wire(members=["Alice"], journal=journal)

    result = await manager.manage_admin(enable=True, target_nickname="Alice")

    assert result == {"user": "Alice", "action": "Invited"}
    assert admins.is_admin("Alice")
    assert driver.admin_invite_clicks == ["管理邀请"]
    assert driver.admin_confirm_actions == ["invite"]
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_manage_admin_already_admin():
    """已经是房管还要邀请：不多点一次开关，并把名单抄成屏幕的样子。"""
    journal = []
    manager, admins, driver = _wire(
        members=["Alice"], admin_invite_label="解除管理", journal=journal
    )

    from ushareiplay.modules.room.domain import AlreadyRoomAdmin

    with pytest.raises(AlreadyRoomAdmin):
        await manager.manage_admin(enable=True, target_nickname="Alice")

    assert admins.is_admin("Alice")
    assert driver.admin_invite_clicks == []
    assert driver.admin_confirm_actions == []
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_manage_admin_dismiss_success():
    """解除房管成功：确认走的是 dismiss 那一个按钮。"""
    journal = []
    manager, admins, driver = _wire(
        members=["Alice"], admin_invite_label="解除管理", journal=journal
    )
    admins.add("Alice")
    assert admins.is_admin("Alice")

    result = await manager.manage_admin(enable=False, target_nickname="Alice")

    assert result == {"user": "Alice", "action": "Dismissed"}
    assert not admins.is_admin("Alice")
    assert driver.admin_invite_clicks == ["解除管理"]
    assert driver.admin_confirm_actions == ["dismiss"]
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_manage_admin_not_admin():
    """还不是房管还要解除：不点开关，并把名单里那条删掉。"""
    journal = []
    manager, admins, driver = _wire(
        members=["Alice"], admin_invite_label="管理邀请", journal=journal
    )
    admins.add("Alice")

    from ushareiplay.modules.room.domain import NotRoomAdmin

    with pytest.raises(NotRoomAdmin):
        await manager.manage_admin(enable=False, target_nickname="Alice")

    assert not admins.is_admin("Alice")
    assert driver.admin_invite_clicks == []
    assert driver.admin_confirm_actions == []
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_admin_command_delegation():
    """命令层只解析参数，其余原样交给注入的 manage-admin 用例。"""
    controller = MagicMock()
    cmd = AdminCommand(controller)

    msg = MessageInfo(content=":admin 1 Bob", nickname="Alice")

    fake_manager = MagicMock()
    fake_manager.manage_admin = AsyncMock(return_value={"user": "Bob", "action": "Invited"})
    controller.manage_admin = fake_manager

    res = await cmd.process(msg, ["1", "Bob"])

    assert res == {"user": "Bob", "action": "Invited"}
    fake_manager.manage_admin.assert_awaited_once_with(True, "Bob", caller="Alice")
