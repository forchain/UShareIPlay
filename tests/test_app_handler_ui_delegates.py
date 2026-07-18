from ushareiplay.core.app_handler import AppHandler
from ushareiplay.core.ui import ElementFinder, GestureHandler, KeyActions, Navigator, UIActions


def test_app_handler_exposes_components_without_ui_delegate_methods():
    handler = object.__new__(AppHandler)
    handler.element_finder = object()
    handler.key_actions = object()
    handler.gesture_handler = object()
    handler.navigator = object()
    handler.ui_actions = object()

    for attribute in (
            "element_finder", "key_actions", "gesture_handler", "navigator", "ui_actions"
    ):
        assert getattr(handler, attribute) is not None

    for method in ("wait_for_element", "switch_to_app", "click_element_at", "navigate_to_element"):
        assert not hasattr(handler, method)


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
