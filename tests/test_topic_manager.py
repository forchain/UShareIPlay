from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from tests.fake_ui import FakeScreen, bind_room_info_window, make_handler
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
    """话题流程里的假元素：点击可把对应弹窗层压到 FakeScreen 上。"""

    def __init__(self, key="", screen=None, on_click=None):
        self.key = key
        self.screen = screen
        self.on_click = on_click
        self.clicked = False
        self.cleared = False
        self.sent_keys = []

    def click(self):
        self.clicked = True
        if self.on_click is not None:
            self.on_click()

    def clear(self):
        self.cleared = True

    def send_keys(self, text):
        self.sent_keys.append(text)


def _topic_elements(screen):
    """主界面常驻的话题入口；点它等于打开房间信息抽屉。"""
    return {
        "room_topic": _Element("room_topic", screen, on_click=lambda: screen.open("edit_topic_entry")),
    }


def _edit_entry(screen, opens=None):
    """抽屉里的编辑入口；点了会拉起编辑层（opens 为 None 表示编辑框没渲染出来）。"""
    def _open():
        if opens:
            screen.open(opens)
    return _Element("edit_topic_entry", screen, on_click=_open)


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
    """编辑入口没找到：必须退掉刚被点开的抽屉，而不是留下一层。"""
    manager = TopicManager.initialize()
    screen = FakeScreen()
    handler = make_handler(screen, elements=_topic_elements(screen))
    bind_room_info_window(handler)
    manager._soul_handler = handler

    handler.element_finder.wait_for_any_element = lambda keys, timeout=10: (None, None)

    result = manager._update_topic_ui("入口未找到")

    assert result == {"error": "Failed to find edit topic entry"}
    assert screen.is_clean(), f"抽屉没退干净: {screen.layers}"
    assert screen.stray_backs == 0


def test_update_topic_ui_input_not_found_closes_dialogs():
    """输入框没找到：抽屉要退掉，且不能多按返回把房间也退掉。"""
    manager = TopicManager.initialize()
    screen = FakeScreen()
    handler = make_handler(screen, elements=_topic_elements(screen))
    bind_room_info_window(handler)
    manager._soul_handler = handler

    handler.element_finder.wait_for_any_element = lambda keys, timeout=10: (
        "edit_topic_entry", _edit_entry(screen)
    )

    result = manager._update_topic_ui("输入框未找到")

    assert result == {"error": "Failed to find topic input"}
    assert screen.is_clean(), f"编辑层/抽屉没退干净: {screen.layers}"
    assert screen.stray_backs == 0


def test_update_topic_ui_confirm_not_found_closes_dialogs():
    """确认按钮没找到：编辑层与抽屉都要退掉。"""
    manager = TopicManager.initialize()
    screen = FakeScreen()
    handler = make_handler(screen, elements=_topic_elements(screen))
    bind_room_info_window(handler)
    manager._soul_handler = handler

    handler.element_finder.wait_for_any_element = lambda keys, timeout=10: (
        "edit_topic_entry", _edit_entry(screen, opens="edit_topic_input")
    )

    result = manager._update_topic_ui("确认未找到")

    assert result == {"error": "Failed to find confirm button"}
    assert screen.is_clean(), f"编辑层/抽屉没退干净: {screen.layers}"
    assert screen.stray_backs == 0


def test_update_topic_ui_throttled_closes_dialogs():
    """被冷却挡下时：编辑框与抽屉都退掉，且不误退到派对主页。"""
    manager = TopicManager.initialize()
    screen = FakeScreen()
    handler = make_handler(screen, elements=_topic_elements(screen))
    bind_room_info_window(handler)
    manager._soul_handler = handler

    def _confirm_click():
        screen.close("edit_topic_input")

    confirm_btn = _Element("edit_topic_confirm", screen, on_click=_confirm_click)

    # 确认按钮住在编辑模态里：编辑框那层在场时才可见
    _base_find = handler.element_finder.try_find_element

    def _find(key, log=False, clickable=False):
        if key == "edit_topic_confirm" and "edit_topic_input" in screen.open_keys:
            return confirm_btn
        return _base_find(key, log=log, clickable=clickable)

    handler.element_finder.try_find_element = _find

    def mock_any(keys, timeout=10):
        if "edit_topic_entry" in keys:
            return "edit_topic_entry", _edit_entry(screen, opens="edit_topic_input")
        if "edit_topic_confirm" in keys:
            return "edit_topic_confirm", confirm_btn
        return None, None

    handler.element_finder.wait_for_any_element = mock_any

    result = manager._update_topic_ui("过于频繁")

    assert result == {"error": "update topic too frequently"}
    assert screen.is_clean(), f"编辑框/抽屉没退干净: {screen.layers}"
    assert screen.stray_backs == 0


def test_update_topic_ui_closes_the_drawer_even_when_an_interaction_raises():
    """中途抛异常也要退干净 —— 原先这里是裸 try/except，一层都退不掉。"""
    manager = TopicManager.initialize()
    screen = FakeScreen()
    handler = make_handler(screen, elements=_topic_elements(screen))
    bind_room_info_window(handler)
    manager._soul_handler = handler

    def _boom(keys, timeout=10):
        if "edit_topic_entry" in keys:
            return "edit_topic_entry", _edit_entry(screen, opens="edit_topic_input")
        raise RuntimeError("driver died mid-flow")

    handler.element_finder.wait_for_any_element = _boom

    result = manager._update_topic_ui("异常")

    assert "error" in result
    assert screen.is_clean(), f"异常路径残留了弹窗: {screen.layers}"
    assert screen.stray_backs == 0


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

