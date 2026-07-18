from types import SimpleNamespace
from unittest.mock import Mock

from ushareiplay.core.ui.gesture_handler import GestureHandler
from ushareiplay.core.ui.navigation import Navigator


def test_navigator_uses_explicit_ui_components_after_delegate_removal():
    target = object()
    owner = SimpleNamespace(
        driver=Mock(),
        config={},
        logger=Mock(),
        key_actions=Mock(),
        element_finder=Mock(),
        gesture_handler=Mock(),
    )
    owner.element_finder.wait_for_any_element.return_value = ("search_box", target)
    owner.element_finder.try_find_any_element.return_value = (None, None)

    assert Navigator(owner).navigate_to_element("search_box") == ("search_box", target)

    owner.key_actions.press_back.assert_called_once_with()
    owner.element_finder.wait_for_any_element.assert_called_once()


def test_gesture_handler_uses_element_finder_for_container_lookup():
    container = SimpleNamespace(
        location={"x": 0, "y": 0}, size={"width": 100, "height": 100}
    )
    owner = SimpleNamespace(
        driver=Mock(page_source="<page />"),
        config={},
        logger=Mock(),
        element_finder=Mock(),
    )
    owner.element_finder.wait_for_element_clickable.return_value = container
    owner.element_finder.find_child_element.return_value = None

    assert GestureHandler(owner).scroll_container_until_element("message", "message_list") == (
        None, None, []
    )

    owner.element_finder.wait_for_element_clickable.assert_called_once_with("message_list")
