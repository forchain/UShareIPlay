import pytest

from ushareiplay.managers.admin_manager import AdminManager
from ushareiplay.managers.online_drawer import OnlineDrawerManager
from ushareiplay.commands.admin import AdminCommand
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.core.roles import RolePolicy
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


class _Handler:
    """最小 handler：抽屉会话只用到 logger，controller 缺席即不加 UI 锁。"""

    def __init__(self):
        self.logger = None
        self.controller = None


def _wire(*, members=("Alice",), name_resolver=None, admin_invite_label="管理邀请", **driver_kwargs):
    """装好抽屉会话与 `AdminManager`，把真实屏幕交给内存替身。

    #439 起房管流程全程走抽屉会话：找人在会话里点资料卡，点开关与点确认框都在资料卡上，
    因此断言的对象从「Appium 元素被点了几次」变成「抽屉替身上留下了什么」。
    """
    AdminManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    driver = InMemoryOnlineDrawerDriver(
        members=list(members), admin_invite_label=admin_invite_label, **driver_kwargs
    )
    OnlineDrawerManager.initialize(
        handler=_Handler(), driver=driver, name_resolver=name_resolver
    )
    manager = AdminManager.initialize(_Handler())
    return manager, driver


@pytest.fixture(autouse=True)
def reset_admin_manager():
    AdminManager.reset_instance()
    OnlineDrawerManager.reset_instance()
    yield
    AdminManager.reset_instance()
    OnlineDrawerManager.reset_instance()


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
    """邀请房管成功：点一次开关、点一次确认，记上本地房管名单，三层都收干净。

    「点了几次」这条断言没被削弱，只是换了观察口：旧实现断言 Appium 元素
    `click.assert_called_once()`，现在断言替身上开关点过一次（`admin_invite_clicks`）
    且确认的动作是 invite（`admin_confirm_actions`）—— 两者都精确到「恰好一次」。
    """
    journal = []
    manager, driver = _wire(members=["Alice"], journal=journal)

    result = await manager.manage_admin(enable=True, target_nickname="Alice")

    assert result == {"user": "Alice", "action": "Invited"}
    assert manager.is_room_admin("Alice")
    assert driver.admin_invite_clicks == ["管理邀请"]
    assert driver.admin_confirm_actions == ["invite"]
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_manage_admin_already_admin():
    """已经是房管还要邀请：只回报一句，不多点一次开关，并把本地名单抄成屏幕的样子。

    旧实现在这条分支上是 `press_back` + `close_drawer` 收场；现在由抽屉会话的收尾
    兜住，而「不接受一次多余的邀请」这个断言本身没变。
    """
    journal = []
    manager, driver = _wire(
        members=["Alice"], admin_invite_label="解除管理", journal=journal  # UI shows it's already an admin
    )

    result = await manager.manage_admin(enable=True, target_nickname="Alice")

    assert result == {"error": "你已经是管理员了", "user": "Alice"}
    # Should be recognized as room admin
    assert manager.is_room_admin("Alice")
    # 屏幕说的是「解除管理」，邀请是个多余动作：那一次点击与那次确认都不该发生。
    assert driver.admin_invite_clicks == []
    assert driver.admin_confirm_actions == []
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_manage_admin_dismiss_success():
    """解除房管成功：确认走的是 dismiss 那一个按钮。

    邀请与解除在 App 上共用同一枚开关，只是确认框里点的按钮不同 —— 断言确认动作是
    dismiss，是用来盯住「别把两个动作点串了」。
    """
    journal = []
    manager, driver = _wire(
        members=["Alice"], admin_invite_label="解除管理", journal=journal
    )
    manager.add_room_admin("Alice")
    assert manager.is_room_admin("Alice")

    result = await manager.manage_admin(enable=False, target_nickname="Alice")

    assert result == {"user": "Alice", "action": "Dismissed"}
    assert not manager.is_room_admin("Alice")
    assert driver.admin_invite_clicks == ["解除管理"]
    assert driver.admin_confirm_actions == ["dismiss"]
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_manage_admin_not_admin():
    """还不是房管还要解除：同样只回报一句，并把本地名单里那条删掉。"""
    journal = []
    manager, driver = _wire(
        members=["Alice"], admin_invite_label="管理邀请", journal=journal  # UI shows it is NOT an admin
    )
    manager.add_room_admin("Alice")

    result = await manager.manage_admin(enable=False, target_nickname="Alice")

    assert result == {"error": "你还不是管理员", "user": "Alice"}
    # Should be removed from room admins
    assert not manager.is_room_admin("Alice")
    assert driver.admin_invite_clicks == []
    assert driver.admin_confirm_actions == []
    assert driver.admin_confirm_pending is False
    assert driver.card_open is False
    assert driver.drawer_open is False
    assert not any("back" in event for event in journal), journal


@pytest.mark.asyncio
async def test_admin_command_delegation():
    """命令层只解析参数，其余原样交出去 —— 两条断言都没变，变的只是打桩的位置。

    #439 之前命令在 `__init__` 里把单例抓成 `self.admin_manager`，那时在构造期就查了
    一次单例；现在与 `GiftCommand` 同形，在 `do_process` 里查，打桩也就跟着落在
    `AdminManager.instance` 上。
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    AdminManager.initialize()
    controller = MagicMock()
    cmd = AdminCommand(controller)

    msg = MessageInfo(
        content=":admin 1 Bob",
        nickname="Alice",
    )

    fake_manager = MagicMock()
    fake_manager.manage_admin = AsyncMock(return_value={"user": "Bob", "action": "Invited"})

    with patch("ushareiplay.commands.admin.AdminManager.instance", return_value=fake_manager):
        res = await cmd.process(msg, ["1", "Bob"])

    assert res == {"user": "Bob", "action": "Invited"}
    fake_manager.manage_admin.assert_awaited_once_with(True, "Bob")
