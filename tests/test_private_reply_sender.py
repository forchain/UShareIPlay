from unittest.mock import MagicMock

from appium.webdriver.common.appiumby import AppiumBy

from ushareiplay.managers.user_manager import UserManager


def _make_manager():
    manager = UserManager.__new__(UserManager)
    manager._handler = MagicMock()
    manager._logger = MagicMock()
    return manager


def test_send_private_message_to_user_success_path():
    manager = _make_manager()
    manager.open_user_profile_from_online_list = MagicMock(return_value={})

    avatar = MagicMock()
    private_btn = MagicMock()
    input_box = MagicMock()
    send_btn = MagicMock()
    room_back = MagicMock()

    manager.handler.wait_for_element_clickable.side_effect = [
        avatar,
        private_btn,
        input_box,
        send_btn,
        room_back,
    ]

    ok = manager.send_private_message_to_user("Alice", "hello")

    assert ok is True
    manager.open_user_profile_from_online_list.assert_called_once_with("Alice")
    input_box.send_keys.assert_called_once_with("hello")
    avatar.click.assert_called_once()
    private_btn.click.assert_called_once()
    send_btn.click.assert_called_once()
    room_back.click.assert_called_once()
    manager.handler.wait_for_element_clickable_plus.assert_not_called()
    manager.handler.wait_for_element_clickable.assert_any_call(
        AppiumBy.ID, 'cn.soulapp.android:id/ivAvatar', timeout=5
    )


def test_send_private_message_to_user_fallback_to_floating_entry():
    manager = _make_manager()
    manager.open_user_profile_from_online_list = MagicMock(return_value={})

    avatar = MagicMock()
    private_btn = MagicMock()
    input_box = MagicMock()
    send_btn = MagicMock()
    floating_entry = MagicMock()

    manager.handler.wait_for_element_clickable.side_effect = [
        avatar,
        private_btn,
        input_box,
        send_btn,
        None,
    ]
    manager.handler.wait_for_element_clickable_plus.return_value = floating_entry

    ok = manager.send_private_message_to_user("Bob", "hi")

    assert ok is True
    manager.handler.wait_for_element_clickable_plus.assert_called_once_with('floating_entry', timeout=3)
    floating_entry.click.assert_called_once()


def test_send_private_message_to_user_failure_returns_false():
    manager = _make_manager()
    manager.open_user_profile_from_online_list = MagicMock(return_value={})

    avatar = MagicMock()
    manager.handler.wait_for_element_clickable.side_effect = [
        avatar,
        None,
    ]

    ok = manager.send_private_message_to_user("Carol", "hey")

    assert ok is False
    avatar.click.assert_called_once()
    manager.logger.warning.assert_called()
