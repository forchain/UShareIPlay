import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ushareiplay.managers.admin_manager import AdminManager
from ushareiplay.commands.admin import AdminCommand
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.core.roles import RolePolicy


@pytest.fixture(autouse=True)
def reset_admin_manager():
    AdminManager.reset_instance()
    yield
    AdminManager.reset_instance()


def test_admin_manager_room_admin_crud():
    manager = AdminManager.initialize()
    assert manager.get_room_admins() == set()
    assert not manager.is_room_admin("Alice")

    manager.add_room_admin("Alice")
    assert manager.is_room_admin("Alice")
    assert manager.get_room_admins() == {"Alice"}
    # Safe copy returned
    admins = manager.get_room_admins()
    admins.add("Bob")
    assert manager.get_room_admins() == {"Alice"}

    manager.add_room_admin("Bob")
    assert manager.is_room_admin("Bob")
    assert manager.get_room_admins() == {"Alice", "Bob"}

    manager.remove_room_admin("Alice")
    assert not manager.is_room_admin("Alice")
    assert manager.get_room_admins() == {"Bob"}

    # Removing non-existent user should not error
    manager.remove_room_admin("NonExistent")
    assert manager.get_room_admins() == {"Bob"}

    manager.clear_room_admins()
    assert manager.get_room_admins() == set()


def test_room_admin_decoupled_from_role_policy():
    manager = AdminManager.initialize()
    config = {
        "soul": {
            "owner": "OwnerUser",
            "admins": ["ConfigAdmin1", "ConfigAdmin2"],
        }
    }
    policy = RolePolicy(config)
    assert policy.is_admin("ConfigAdmin1")
    # RolePolicy admin is not automatically in AdminManager room admins
    assert not manager.is_room_admin("ConfigAdmin1")

    # Adding room admin doesn't make them RolePolicy admin if not configured
    manager.add_room_admin("RoomOnlyAdmin")
    assert manager.is_room_admin("RoomOnlyAdmin")
    assert not policy.is_admin("RoomOnlyAdmin")


@pytest.mark.asyncio
async def test_manage_admin_invite_success():
    manager = AdminManager.initialize()
    mock_handler = MagicMock()
    manager._handler = mock_handler
    manager._logger = MagicMock()

    mock_invite_elem = MagicMock()
    mock_invite_elem.text = "管理邀请"
    mock_confirm_elem = MagicMock()

    mock_handler.element_finder.wait_for_element_clickable.side_effect = lambda key: (
        mock_invite_elem if key == "manager_invite" else (
            mock_confirm_elem if key == "confirm_invite" else None
        )
    )

    with patch("ushareiplay.managers.user_manager.UserManager.instance") as mock_user_mgr_cls, \
         patch("ushareiplay.managers.recovery_manager.RecoveryManager.instance") as mock_rec_mgr_cls:
        mock_user_mgr = MagicMock()
        # manage_admin 走异步的身份感知入口 open_user_profile（跨命名域按身份判定）
        mock_user_mgr.open_user_profile = AsyncMock(return_value={"user": "Alice"})
        mock_user_mgr_cls.return_value = mock_user_mgr

        mock_rec_mgr = MagicMock()
        mock_rec_mgr_cls.return_value = mock_rec_mgr

        result = await manager.manage_admin(enable=True, target_nickname="Alice")

        assert result == {"user": "Alice", "action": "Invited"}
        assert manager.is_room_admin("Alice")
        mock_invite_elem.click.assert_called_once()
        mock_confirm_elem.click.assert_called_once()


@pytest.mark.asyncio
async def test_manage_admin_already_admin():
    manager = AdminManager.initialize()
    mock_handler = MagicMock()
    manager._handler = mock_handler
    manager._logger = MagicMock()

    mock_invite_elem = MagicMock()
    mock_invite_elem.text = "解除管理"  # UI shows it's already an admin

    mock_handler.element_finder.wait_for_element_clickable.side_effect = lambda key: (
        mock_invite_elem if key == "manager_invite" else None
    )

    with patch("ushareiplay.managers.user_manager.UserManager.instance") as mock_user_mgr_cls, \
         patch("ushareiplay.managers.recovery_manager.RecoveryManager.instance") as mock_rec_mgr_cls:
        mock_user_mgr = MagicMock()
        # manage_admin 走异步的身份感知入口 open_user_profile（跨命名域按身份判定）
        mock_user_mgr.open_user_profile = AsyncMock(return_value={"user": "Alice"})
        mock_user_mgr_cls.return_value = mock_user_mgr

        mock_rec_mgr = MagicMock()
        mock_rec_mgr_cls.return_value = mock_rec_mgr

        result = await manager.manage_admin(enable=True, target_nickname="Alice")

        assert result == {"error": "你已经是管理员了", "user": "Alice"}
        # Should be recognized as room admin
        assert manager.is_room_admin("Alice")
        mock_handler.key_actions.press_back.assert_called_once()


@pytest.mark.asyncio
async def test_manage_admin_dismiss_success():
    manager = AdminManager.initialize()
    manager.add_room_admin("Alice")
    assert manager.is_room_admin("Alice")

    mock_handler = MagicMock()
    manager._handler = mock_handler
    manager._logger = MagicMock()

    mock_invite_elem = MagicMock()
    mock_invite_elem.text = "解除管理"
    mock_confirm_elem = MagicMock()

    mock_handler.element_finder.wait_for_element_clickable.side_effect = lambda key: (
        mock_invite_elem if key == "manager_invite" else (
            mock_confirm_elem if key == "confirm_dismiss" else None
        )
    )

    with patch("ushareiplay.managers.user_manager.UserManager.instance") as mock_user_mgr_cls, \
         patch("ushareiplay.managers.recovery_manager.RecoveryManager.instance") as mock_rec_mgr_cls:
        mock_user_mgr = MagicMock()
        # manage_admin 走异步的身份感知入口 open_user_profile（跨命名域按身份判定）
        mock_user_mgr.open_user_profile = AsyncMock(return_value={"user": "Alice"})
        mock_user_mgr_cls.return_value = mock_user_mgr

        mock_rec_mgr = MagicMock()
        mock_rec_mgr_cls.return_value = mock_rec_mgr

        result = await manager.manage_admin(enable=False, target_nickname="Alice")

        assert result == {"user": "Alice", "action": "Dismissed"}
        assert not manager.is_room_admin("Alice")
        mock_invite_elem.click.assert_called_once()
        mock_confirm_elem.click.assert_called_once()


@pytest.mark.asyncio
async def test_manage_admin_not_admin():
    manager = AdminManager.initialize()
    manager.add_room_admin("Alice")

    mock_handler = MagicMock()
    manager._handler = mock_handler
    manager._logger = MagicMock()

    mock_invite_elem = MagicMock()
    mock_invite_elem.text = "管理邀请"  # UI shows it is NOT an admin

    mock_handler.element_finder.wait_for_element_clickable.side_effect = lambda key: (
        mock_invite_elem if key == "manager_invite" else None
    )

    with patch("ushareiplay.managers.user_manager.UserManager.instance") as mock_user_mgr_cls, \
         patch("ushareiplay.managers.recovery_manager.RecoveryManager.instance") as mock_rec_mgr_cls:
        mock_user_mgr = MagicMock()
        # manage_admin 走异步的身份感知入口 open_user_profile（跨命名域按身份判定）
        mock_user_mgr.open_user_profile = AsyncMock(return_value={"user": "Alice"})
        mock_user_mgr_cls.return_value = mock_user_mgr

        mock_rec_mgr = MagicMock()
        mock_rec_mgr_cls.return_value = mock_rec_mgr

        result = await manager.manage_admin(enable=False, target_nickname="Alice")

        assert result == {"error": "你还不是管理员", "user": "Alice"}
        # Should be removed from room admins
        assert not manager.is_room_admin("Alice")
        mock_handler.key_actions.press_back.assert_called_once()


@pytest.mark.asyncio
async def test_admin_command_delegation():
    AdminManager.initialize()
    controller = MagicMock()
    cmd = AdminCommand(controller)

    msg = MessageInfo(
        content=":admin 1 Bob",
        nickname="Alice",
    )

    with patch.object(cmd.admin_manager, "manage_admin", new_callable=AsyncMock) as mock_manage:
        mock_manage.return_value = {"user": "Bob", "action": "Invited"}
        res = await cmd.process(msg, ["1", "Bob"])
        assert res == {"user": "Bob", "action": "Invited"}
        mock_manage.assert_awaited_once_with(True, "Bob")
