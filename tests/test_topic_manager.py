from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from ushareiplay.managers.topic_manager import TopicManager


@pytest.fixture(autouse=True)
def _reset_topic_manager():
    TopicManager.reset_instance()
    yield
    TopicManager.reset_instance()


class _FakeSoulHandler:
    def __init__(self):
        self.logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = True


def test_change_topic_sanitizes_fullwidth_pipe_and_parentheses():
    manager = TopicManager.initialize()
    manager._soul_handler = _FakeSoulHandler()

    result = manager.change_topic("经典老歌（粤语）｜extra")

    assert manager.next_topic == "经典老歌"
    assert "Topic will update soon" in result["topic"]


def test_change_topic_sanitizes_halfwidth_pipe_and_parentheses():
    manager = TopicManager.initialize()
    manager._soul_handler = _FakeSoulHandler()

    result = manager.change_topic("流行金曲 (国语) | extra")

    assert manager.next_topic == "流行金曲"
    assert "Topic will update soon" in result["topic"]


class _Element:
    def __init__(self, key=""):
        self.key = key
        self.clicked = False
        self.cleared = False
        self.sent_keys = []

    def click(self):
        self.clicked = True

    def clear(self):
        self.cleared = True

    def send_keys(self, text):
        self.sent_keys.append(text)


class _MockSoulHandler:
    def __init__(self):
        self.logger = SimpleNamespace(
            info=lambda *a, **k: None,
            error=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            debug=lambda *a, **k: None,
        )
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = True
        self.element_finder = MagicMock()


def test_update_topic_ui_success():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    room_topic = _Element("room_topic")
    edit_entry = _Element("edit_topic_entry")
    topic_input = _Element("edit_topic_input")
    confirm_btn = _Element("edit_topic_confirm")
    input_box = _Element("input_box_entry")

    def mock_clickable(key, timeout=10):
        if key == "room_topic":
            return room_topic
        elif key == "edit_topic_input":
            return topic_input
        elif key == "edit_topic_confirm":
            return confirm_btn
        return None

    handler.element_finder.wait_for_element_clickable.side_effect = mock_clickable

    def mock_any_element(keys, timeout=10):
        if "edit_topic_entry" in keys:
            return ("edit_topic_entry", edit_entry)
        if "input_box_entry" in keys:
            return ("input_box_entry", input_box)
        return (None, None)

    handler.element_finder.wait_for_any_element.side_effect = mock_any_element

    result = manager._update_topic_ui("测试话题")

    assert result == {"success": True, "topic": "测试话题"}
    assert room_topic.clicked is True
    assert edit_entry.clicked is True
    assert topic_input.cleared is True
    assert topic_input.sent_keys == ["测试话题"]
    assert confirm_btn.clicked is True
    assert handler.key_actions.press_back.call_count == 0


def test_update_topic_ui_fallback_to_bg_entry():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    room_topic = _Element("room_topic")
    edit_bg_entry = _Element("edit_topic_bg_entry")
    topic_input = _Element("edit_topic_input")
    confirm_btn = _Element("edit_topic_confirm")
    input_box = _Element("input_box_entry")

    handler.element_finder.wait_for_element_clickable.side_effect = lambda k, **kw: {
        "room_topic": room_topic,
        "edit_topic_input": topic_input,
        "edit_topic_confirm": confirm_btn,
    }.get(k)

    def mock_any(keys, timeout=10):
        if "edit_topic_bg_entry" in keys:
            return ("edit_topic_bg_entry", edit_bg_entry)
        if "input_box_entry" in keys:
            return ("input_box_entry", input_box)
        return (None, None)

    handler.element_finder.wait_for_any_element.side_effect = mock_any

    result = manager._update_topic_ui("背景主题")

    assert result == {"success": True, "topic": "背景主题"}
    assert room_topic.clicked is True
    assert edit_bg_entry.clicked is True


def test_update_topic_ui_in_guest_room():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    from ushareiplay.state.room_state import RoomState
    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    try:
        result = manager._update_topic_ui("客人房间")
        assert result == {"skipped": "guest_room"}
        assert handler.element_finder.wait_for_element_clickable.call_count == 0
    finally:
        RoomState.reset_instance()


def test_update_topic_ui_room_topic_not_found():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    handler.element_finder.wait_for_element_clickable.return_value = None

    result = manager._update_topic_ui("未找到")

    assert result == {"error": "Failed to find room topic"}


def test_update_topic_ui_edit_entry_not_found_closes_dialog():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    room_topic = _Element("room_topic")
    handler.element_finder.wait_for_element_clickable.side_effect = lambda k, **kw: (
        room_topic if k == "room_topic" else None
    )
    handler.element_finder.wait_for_any_element.return_value = (None, None)

    result = manager._update_topic_ui("入口未找到")

    assert result == {"error": "Failed to find edit topic entry"}
    assert room_topic.clicked is True
    assert handler.key_actions.press_back.call_count == 1


def test_update_topic_ui_input_not_found_closes_dialogs():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    room_topic = _Element("room_topic")
    edit_entry = _Element("edit_topic_entry")

    handler.element_finder.wait_for_element_clickable.side_effect = lambda k, **kw: (
        room_topic if k == "room_topic" else None
    )
    handler.element_finder.wait_for_any_element.return_value = ("edit_topic_entry", edit_entry)

    result = manager._update_topic_ui("输入框未找到")

    assert result == {"error": "Failed to find topic input"}
    assert handler.key_actions.press_back.call_count == 2


def test_update_topic_ui_confirm_not_found_closes_dialogs():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    room_topic = _Element("room_topic")
    edit_entry = _Element("edit_topic_entry")
    topic_input = _Element("edit_topic_input")

    handler.element_finder.wait_for_element_clickable.side_effect = lambda k, **kw: {
        "room_topic": room_topic,
        "edit_topic_input": topic_input,
    }.get(k)
    handler.element_finder.wait_for_any_element.return_value = ("edit_topic_entry", edit_entry)

    result = manager._update_topic_ui("确认未找到")

    assert result == {"error": "Failed to find confirm button"}
    assert handler.key_actions.press_back.call_count == 2


def test_update_topic_ui_throttled_closes_dialogs():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    room_topic = _Element("room_topic")
    edit_entry = _Element("edit_topic_entry")
    topic_input = _Element("edit_topic_input")
    confirm_btn = _Element("edit_topic_confirm")

    handler.element_finder.wait_for_element_clickable.side_effect = lambda k, **kw: {
        "room_topic": room_topic,
        "edit_topic_input": topic_input,
        "edit_topic_confirm": confirm_btn,
    }.get(k)

    def mock_any(keys, timeout=10):
        if "edit_topic_entry" in keys:
            return ("edit_topic_entry", edit_entry)
        if "edit_topic_confirm" in keys:
            return ("edit_topic_confirm", confirm_btn)
        return (None, None)

    handler.element_finder.wait_for_any_element.side_effect = mock_any

    result = manager._update_topic_ui("过于频繁")

    assert result == {"error": "update topic too frequently"}
    assert handler.key_actions.press_back.call_count == 3


def test_topic_manager_update_success_clears_next_topic():
    manager = TopicManager.initialize()
    handler = _MockSoulHandler()
    manager._soul_handler = handler

    manager.next_topic = "新话题"
    manager._update_topic_ui = MagicMock(return_value={"success": True, "topic": "新话题"})
    manager._message_dispatch = MagicMock()

    manager.update()

    assert manager.current_topic == "新话题"
    assert manager.next_topic is None
    manager.message_dispatch.send_screen_message.assert_called_once_with("Updating topic to 新话题")

