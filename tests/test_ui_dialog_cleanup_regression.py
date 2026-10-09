import pytest
from unittest.mock import MagicMock, patch

from ushareiplay.managers.admin_manager import AdminManager
from ushareiplay.managers.user_manager import UserManager
from ushareiplay.managers.room_profile.manager import RoomProfileManager
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver


@pytest.fixture(autouse=True)
def reset_managers():
    AdminManager.reset_instance()
    UserManager.reset_instance()
    RoomProfileManager.reset_instance()
    yield
    AdminManager.reset_instance()
    UserManager.reset_instance()
    RoomProfileManager.reset_instance()


@pytest.mark.asyncio
async def test_admin_failure_closes_user_profile_and_online_drawer():
    """当 manager_invite 未找到时，必须关闭已打开的用户资料卡和在线用户抽屉。"""
    handler = MagicMock()
    user_manager = UserManager.initialize(handler=handler)
    admin_manager = AdminManager.initialize(handler=handler)

    user_count_elem = MagicMock()
    user_elem = MagicMock()

    handler.element_finder.wait_for_element.side_effect = lambda key, **kw: (
        user_count_elem if key == 'user_count' else (
            MagicMock() if key == 'online_users' else None
        )
    )
    handler.gesture_handler.scroll_container_until_element.return_value = ('user_item', user_elem, 0)
    handler.element_finder.wait_for_element_clickable.return_value = None  # manager_invite 未找到

    with patch.object(admin_manager, '_close_user_profile_and_online_drawer') as mock_cleanup:
        res = await admin_manager.manage_admin(enable=True, target_nickname="Joyer")
        assert 'error' in res
        mock_cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_send_gift_failure_closes_user_profile_and_online_drawer():
    """当 send_gift 按钮未找到时，必须关闭已打开的用户资料卡和在线用户抽屉。"""
    handler = MagicMock()
    user_manager = UserManager.initialize(handler=handler)

    user_count_elem = MagicMock()
    user_elem = MagicMock()

    handler.element_finder.wait_for_element.side_effect = lambda key, **kw: (
        user_count_elem if key == 'user_count' else (
            MagicMock() if key == 'online_users' else None
        )
    )
    handler.gesture_handler.scroll_container_until_element.return_value = ('user_item', user_elem, 0)
    handler.element_finder.wait_for_element_clickable.return_value = None  # send_gift 按钮未找到

    with patch.object(user_manager, 'close_user_profile_and_online_drawer') as mock_cleanup:
        res = await user_manager.send_gift("Alice")
        assert 'error' in res
        mock_cleanup.assert_called_once()


def test_read_room_title_outside_drawer_does_not_wait_or_timeout_on_dialog_element():
    """抽屉未打开时读房名，不得调用 wait_for_element('room_name_in_dialog') 造成无意义的超时等待。"""
    driver = InMemoryRoomProfileDrawerDriver(drawer_open=False)
    handler = MagicMock()
    handler.config = {'soul': {'default_title': '好心情', 'default_theme': '听歌'}}
    title_elem = MagicMock()
    handler.element_finder.try_find_element.side_effect = lambda key, **kw: (
        title_elem if key == 'chat_room_title' else None
    )
    handler.element_finder.get_element_text.return_value = "听歌｜好心情"

    profile = RoomProfileManager.initialize(
        handler=handler,
        drawer_driver=driver,
    )

    # 抽屉未打开
    assert not profile.is_open()

    title = profile._read_room_title_text_from_ui()
    assert title == "听歌｜好心情"

    # 验证没有调用 wait_for_element('room_name_in_dialog')
    for call in handler.element_finder.wait_for_element.call_args_list:
        assert call[0][0] != 'room_name_in_dialog', "抽屉未打开时禁止 wait_for_element('room_name_in_dialog')"


def test_room_profile_audit_notice_input_failure_dismisses_dialog():
    """公告审计在输入或确认失败时，必须点击 close_notice 关闭留在屏幕上的编辑弹窗。"""
    driver = MagicMock()
    driver.is_open.return_value = True
    driver.click_element.return_value = True
    from ushareiplay.managers.room_profile.manager import (
        NOTICE_CLOSE_KEY,
        NOTICE_CUSTOMIZE_ENTRY_KEYS,
        NOTICE_EDIT_ENTRY_KEY,
    )
    driver.wait_for_any.side_effect = lambda keys, **kw: (
        NOTICE_EDIT_ENTRY_KEY if NOTICE_EDIT_ENTRY_KEY in keys else (
            NOTICE_CLOSE_KEY if NOTICE_CLOSE_KEY in keys else (
                NOTICE_CUSTOMIZE_ENTRY_KEYS[0] if NOTICE_CUSTOMIZE_ENTRY_KEYS[0] in keys else None
            )
        )
    )

    driver.replace_text.return_value = False

    handler = MagicMock()
    handler.config = {'soul': {'system_default_notices': ['default']}}
    profile = RoomProfileManager.initialize(
        handler=handler,
        drawer_driver=driver,
    )

    with patch.object(profile, '_read_notice_text_from_ui', return_value='default'):
        res = profile._audit_notice_in_open_window()
        assert 'error' in res
        assert res['error'] == 'Failed to find notice input'
        # 确认调用了 click_element(NOTICE_CLOSE_KEY)
        driver.click_element.assert_any_call(NOTICE_CLOSE_KEY)


def test_room_profile_ensure_closed_handles_residual_drawer():
    """若第一次 close_drawer 失败，press_back 仅关闭了上层对话框，抽屉仍开着时，ensure_closed 必须继续尝试关闭抽屉。"""
    driver = MagicMock()
    # 模拟状态：初始开着，close_drawer 失败，press_back 之后仍开着，第二次 close_drawer 成功关掉
    driver.is_open.side_effect = [True, True, False]
    driver.close_drawer.side_effect = [False, True]

    handler = MagicMock()
    handler.config = {'soul': {}}
    profile = RoomProfileManager.initialize(
        handler=handler,
        drawer_driver=driver,
    )

    profile.ensure_closed()
    assert driver.close_drawer.call_count == 2
    assert driver.press_back.call_count == 1


def test_room_profile_ensure_closed_handles_close_drawer_true_but_subdialog_remains():
    """即使 close_drawer 返回 True，但由于子弹窗遮挡导致 is_open 仍为 True，必须继续按返回键并关闭残留抽屉。"""
    driver = MagicMock()
    # close_drawer 返回 True，但 is_open 依然为 True（子对话框仍在），press_back 后 is_open 依然为 True（抽屉主体还在），第二次 close_drawer 彻底关闭
    driver.is_open.side_effect = [True, True, True, False]
    driver.close_drawer.side_effect = [True, True]

    handler = MagicMock()
    handler.config = {'soul': {}}
    profile = RoomProfileManager.initialize(
        handler=handler,
        drawer_driver=driver,
    )

    profile.ensure_closed()
    assert driver.close_drawer.call_count == 2
    assert driver.press_back.call_count == 1


def test_dialog_keys_includes_all_subdialog_elements():
    """DIALOG_KEYS 必须包含所有子弹窗及编辑层控件，避免 is_open 漏判。"""
    from ushareiplay.managers.room_profile.driver import DIALOG_KEYS
    expected_subdialog_keys = {
        'edit_topic_confirm',
        'edit_topic_input',
        'close_notice',
        'edit_notice_input',
        'edit_notice_confirm',
        'title_edit_input',
        'title_edit_confirm',
        'party_recommendation_close',
        'party_recommendation_open',
        'room_name_in_dialog',
    }
    assert expected_subdialog_keys.issubset(set(DIALOG_KEYS))


def test_read_room_title_inside_drawer_uses_try_find_element():
    """抽屉打开时读房名，优先使用 try_find_element('room_name_in_dialog', log=False) 且成功返回文本。"""
    driver = MagicMock()
    driver.is_open.return_value = True

    handler = MagicMock()
    handler.config = {'soul': {}}
    dialog_elem = MagicMock()
    handler.element_finder.try_find_element.side_effect = lambda key, **kw: (
        dialog_elem if key == 'room_name_in_dialog' else None
    )
    handler.element_finder.get_element_text.return_value = "音乐｜自习时光"

    profile = RoomProfileManager.initialize(
        handler=handler,
        drawer_driver=driver,
    )

    title = profile._read_room_title_text_from_ui()
    assert title == "音乐｜自习时光"
    # 确保没有调用 wait_for_element
    assert handler.element_finder.wait_for_element.call_count == 0


def test_is_chat_window_open_detects_input_drawer():
    """当 input_box 不存在但 input_drawer 存在且可见时，is_chat_window_open 必须返回 True。"""
    from ushareiplay.handlers.soul_handler import SoulHandler
    handler = SoulHandler.__new__(SoulHandler)
    handler.element_finder = MagicMock()

    drawer_elem = MagicMock()
    drawer_elem.is_displayed.return_value = True

    def mock_try_find(key, **kw):
        if key == 'input_drawer':
            return drawer_elem
        return None

    handler.element_finder.try_find_element.side_effect = mock_try_find
    assert handler.is_chat_window_open() is True


def test_ensure_chat_window_closed_closes_input_drawer():
    """当 input_drawer 存在时，ensure_chat_window_closed 会调用 RecoveryManager.close_drawer('input_drawer')。"""
    from ushareiplay.handlers.soul_handler import SoulHandler
    from ushareiplay.managers.recovery_manager import RecoveryManager

    handler = SoulHandler.__new__(SoulHandler)
    handler.logger = MagicMock()
    handler.element_finder = MagicMock()
    handler.gesture_handler = MagicMock()
    handler.key_actions = MagicMock()

    drawer_elem = MagicMock()
    drawer_elem.is_displayed.return_value = True

    drawer_state = {'open': True}

    def mock_try_find(key, **kw):
        if key == 'input_drawer' and drawer_state['open']:
            return drawer_elem
        return None

    handler.element_finder.try_find_element.side_effect = mock_try_find
    handler.element_finder.wait_for_element_disappear.return_value = True

    rec_mock = MagicMock()

    def mock_close_drawer(drawer_key):
        if drawer_key == 'input_drawer':
            drawer_state['open'] = False
            return True
        return False

    rec_mock.close_drawer.side_effect = mock_close_drawer

    RecoveryManager.reset_instance()
    with patch.object(RecoveryManager, 'is_initialized', return_value=True), \
         patch.object(RecoveryManager, 'instance', return_value=rec_mock):
        closed = handler.ensure_chat_window_closed()
        assert closed is True
        rec_mock.close_drawer.assert_called_with('input_drawer')
        assert handler.is_chat_window_open() is False


