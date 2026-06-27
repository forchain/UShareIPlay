from ushareiplay.core.app_handler import AppHandler
from ushareiplay.core.ui import ElementFinder, GestureHandler, KeyActions, Navigator


class RecordingHelper:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return name, args, kwargs

        return method


def test_app_handler_delegates_ui_helper_methods():
    handler = object.__new__(AppHandler)
    handler.element_finder = RecordingHelper()
    handler.key_actions = RecordingHelper()
    handler.gesture_handler = RecordingHelper()
    handler.navigator = RecordingHelper()

    cases = [
        ("element_finder", "wait_for_element", ("search_box",), {"timeout": 3}, ("wait_for_element", ("search_box",), {"timeout": 3})),
        ("element_finder", "wait_for_element", ("search_box",), {}, ("wait_for_element", ("search_box",), {"timeout": 10})),
        ("element_finder", "is_element_clickable", ("element",), {}, ("is_element_clickable", ("element",), {})),
        ("element_finder", "wait_for_element_clickable", ("search_box",), {}, ("wait_for_element_clickable", ("search_box",), {"timeout": 10})),
        ("element_finder", "try_find_element", ("search_box",), {"log": True}, ("try_find_element", ("search_box",), {"log": True, "clickable": False})),
        ("element_finder", "try_find_element", ("search_box",), {}, ("try_find_element", ("search_box",), {"log": False, "clickable": False})),
        ("element_finder", "wait_for_element_polling", ("id", "value"), {}, ("wait_for_element_polling", ("id", "value"), {"timeout": 10, "poll_frequency": 0.5})),
        ("element_finder", "wait_for_element_clickable_polling", ("id", "value"), {}, ("wait_for_element_clickable_polling", ("id", "value"), {"timeout": 10, "poll_frequency": 0.5})),
        ("element_finder", "find_child_element", ("parent", "child"), {}, ("find_child_element", ("parent", "child"), {"log_failure": True})),
        ("element_finder", "find_child_element", ("parent", "child"), {"log_failure": False}, ("find_child_element", ("parent", "child"), {"log_failure": False})),
        ("element_finder", "find_child_elements", ("parent", "child"), {}, ("find_child_elements", ("parent", "child"), {})),
        ("element_finder", "get_element_text", ("element",), {}, ("get_element_text", ("element",), {})),
        ("element_finder", "try_get_attribute", ("element", "text"), {}, ("try_get_attribute", ("element", "text"), {})),
        ("element_finder", "_get_locator", ("search_box",), {}, ("_get_locator", ("search_box",), {})),
        ("element_finder", "find_elements", ("search_box",), {}, ("find_elements", ("search_box",), {})),
        ("element_finder", "find_child_element", ("parent", "child"), {}, ("find_child_element", ("parent", "child"), {"log_failure": True})),
        ("element_finder", "find_child_elements", ("parent", "child"), {}, ("find_child_elements", ("parent", "child"), {})),
        ("element_finder", "wait_for_any_element", (["a", "b"],), {}, ("wait_for_any_element", (["a", "b"],), {"timeout": 10})),
        ("element_finder", "try_find_any_element", (["a", "b"],), {}, ("try_find_any_element", (["a", "b"],), {})),
        ("key_actions", "switch_to_app", (), {}, ("switch_to_app", (), {})),
        ("key_actions", "close_app", (), {}, ("close_app", (), {})),
        ("key_actions", "switch_to_activity", ("Activity",), {}, ("switch_to_activity", ("Activity",), {})),
        ("key_actions", "press_enter", ("element",), {}, ("press_enter", ("element",), {})),
        ("key_actions", "press_back", (), {}, ("press_back", (), {})),
        ("key_actions", "press_dpad_down", (), {}, ("press_dpad_down", (), {})),
        ("key_actions", "press_volume_up", (), {}, ("press_volume_up", (), {})),
        ("key_actions", "press_volume_down", (), {}, ("press_volume_down", (), {})),
        ("key_actions", "press_right_key", (), {"times": 2}, ("press_right_key", (), {"times": 2})),
        ("key_actions", "set_clipboard_text", ("hello",), {}, ("set_clipboard_text", ("hello",), {})),
        ("key_actions", "paste_text", (), {}, ("paste_text", (), {})),
        ("gesture_handler", "click_element_at", ("element",), {"x_ratio": 0.2}, ("click_element_at", ("element",), {"x_ratio": 0.2, "y_ratio": 0.5, "x_offset": 0, "y_offset": 0})),
        ("gesture_handler", "_perform_swipe", (1, 2, 3, 4), {}, ("_perform_swipe", (1, 2, 3, 4), {"duration_ms": 300})),
        ("gesture_handler", "_reversed_if_needed", ([1, 2], "down"), {}, ("_reversed_if_needed", ([1, 2], "down"), {})),
        ("gesture_handler", "scroll_container_until_element", ("item", "container"), {}, ("scroll_container_until_element", ("item", "container"), {"direction": "up", "attribute_name": None, "attribute_value": None, "max_swipes": 10})),
        ("navigator", "navigate_to_element", ("target",), {"max_attempts": 1}, ("navigate_to_element", ("target",), {"interference_keys": None, "home_key": "home_nav", "back_keys": None, "max_attempts": 1})),
    ]

    for helper_name, method_name, args, kwargs, expected_call in cases:
        result = getattr(handler, method_name)(*args, **kwargs)
        assert result == expected_call
        helper = getattr(handler, helper_name)
        assert helper.calls[-1] == expected_call


def test_ui_helper_methods_keep_driver_recovery_wrappers():
    decorated_methods = [
        ElementFinder.wait_for_element,
        ElementFinder.wait_for_element_clickable,
        ElementFinder.try_find_element,
        ElementFinder.wait_for_element_polling,
        ElementFinder.wait_for_element_clickable_polling,
        ElementFinder.find_elements,
        ElementFinder.wait_for_any_element,
        KeyActions.switch_to_app,
        KeyActions.close_app,
        KeyActions.switch_to_activity,
        KeyActions.press_enter,
        KeyActions.press_back,
        KeyActions.press_dpad_down,
        KeyActions.press_volume_up,
        KeyActions.press_volume_down,
        KeyActions.press_right_key,
        KeyActions.set_clipboard_text,
        KeyActions.paste_text,
        GestureHandler.click_element_at,
        GestureHandler._perform_swipe,
        GestureHandler.scroll_container_until_element,
    ]

    for method in decorated_methods:
        assert hasattr(method, "__wrapped__")
