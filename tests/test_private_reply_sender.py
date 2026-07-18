from unittest.mock import MagicMock

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

    manager.handler.element_finder.wait_for_element_clickable.side_effect = [
        avatar,
        private_btn,
        input_box,
        send_btn,
    ]
    manager.handler.element_finder.wait_for_any_element.return_value = ("private_room_entry", room_back)
    manager.handler.gesture_handler.click_element_at.return_value = True

    ok = manager.send_private_message_to_user("Alice", "hello")

    assert ok is True
    manager.open_user_profile_from_online_list.assert_called_once_with("Alice")
    input_box.send_keys.assert_called_once_with("hello")
    avatar.click.assert_not_called()
    manager.handler.gesture_handler.click_element_at.assert_called_once_with(avatar, y_ratio=0.7)
    private_btn.click.assert_called_once()
    send_btn.click.assert_called_once()
    room_back.click.assert_called_once()
    manager.handler.element_finder.wait_for_element_clickable.assert_any_call(
        'sender_avatar', timeout=5
    )
    manager.handler.element_finder.wait_for_any_element.assert_called_once_with(
        ['private_room_entry', 'floating_entry', 'item_left_back'], timeout=3
    )


def test_send_private_message_to_user_fallback_to_floating_entry():
    manager = _make_manager()
    manager.open_user_profile_from_online_list = MagicMock(return_value={})

    avatar = MagicMock()
    private_btn = MagicMock()
    input_box = MagicMock()
    send_btn = MagicMock()
    floating_entry = MagicMock()

    manager.handler.element_finder.wait_for_element_clickable.side_effect = [
        avatar,
        private_btn,
        input_box,
        send_btn,
    ]
    manager.handler.element_finder.wait_for_any_element.return_value = ("floating_entry", floating_entry)
    manager.handler.gesture_handler.click_element_at.return_value = True

    ok = manager.send_private_message_to_user("Bob", "hi")

    assert ok is True
    manager.handler.element_finder.wait_for_any_element.assert_called_once_with(
        ['private_room_entry', 'floating_entry', 'item_left_back'], timeout=3
    )
    floating_entry.click.assert_called_once()


def test_send_private_message_to_user_fallback_to_left_back_and_titlebar_back():
    manager = _make_manager()
    manager.open_user_profile_from_online_list = MagicMock(return_value={})

    avatar = MagicMock()
    private_btn = MagicMock()
    input_box = MagicMock()
    send_btn = MagicMock()
    titlebar_back = MagicMock()

    manager.handler.element_finder.wait_for_element_clickable.side_effect = [
        avatar,
        private_btn,
        input_box,
        send_btn,
        titlebar_back,
    ]
    manager.handler.element_finder.wait_for_any_element.return_value = ("item_left_back", MagicMock())
    manager.handler.gesture_handler.click_element_at.return_value = True

    ok = manager.send_private_message_to_user("Eve", "hi")

    assert ok is True
    manager.handler.element_finder.wait_for_any_element.assert_called_once_with(
        ['private_room_entry', 'floating_entry', 'item_left_back'], timeout=3
    )
    titlebar_back.click.assert_called_once()


def test_send_private_message_to_user_failure_returns_false():
    manager = _make_manager()
    manager.open_user_profile_from_online_list = MagicMock(return_value={})

    avatar = MagicMock()
    manager.handler.element_finder.wait_for_element_clickable.side_effect = [
        avatar,
        None,
    ]
    manager.handler.gesture_handler.click_element_at.return_value = True

    ok = manager.send_private_message_to_user("Carol", "hey")

    assert ok is False
    avatar.click.assert_not_called()
    manager.handler.gesture_handler.click_element_at.assert_called_once_with(avatar, y_ratio=0.7)
    manager.logger.warning.assert_called()


def test_send_private_message_to_user_returns_false_when_avatar_offset_click_fails():
    manager = _make_manager()
    manager.open_user_profile_from_online_list = MagicMock(return_value={})

    avatar = MagicMock()
    manager.handler.element_finder.wait_for_element_clickable.return_value = avatar
    manager.handler.gesture_handler.click_element_at.return_value = False

    ok = manager.send_private_message_to_user("Dana", "hey")

    assert ok is False
    manager.handler.gesture_handler.click_element_at.assert_called_once_with(avatar, y_ratio=0.7)
    manager.logger.warning.assert_called()
