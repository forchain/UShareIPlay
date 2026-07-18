from unittest.mock import Mock

from ushareiplay.core.ui.ui_actions import UIActions


def make_owner():
    owner = Mock()
    owner.key_actions.switch_to_app.return_value = True
    owner.element_finder.wait_for_element_clickable.return_value = Mock()
    owner.gesture_handler.click_element_at.return_value = True
    return owner


def test_switch_and_click_switches_the_owner_app_and_clicks_element():
    owner = make_owner()

    result = UIActions(owner).switch_and_click(
        "confirm", error_message="Could not confirm", timeout=3, click_kwargs={"y_ratio": 0.25}
    )

    assert result == {"success": True}
    owner.key_actions.switch_to_app.assert_called_once_with()
    owner.element_finder.wait_for_element_clickable.assert_called_once_with("confirm", timeout=3)
    owner.gesture_handler.click_element_at.assert_called_once_with(
        owner.element_finder.wait_for_element_clickable.return_value, y_ratio=0.25
    )


def test_switch_and_click_returns_switch_error_without_finding_an_element():
    owner = make_owner()
    owner.key_actions.switch_to_app.return_value = False

    result = UIActions(owner).switch_and_click("confirm", error_message="Could not confirm")

    assert result == {"error": "Failed to switch to app"}
    owner.element_finder.wait_for_element_clickable.assert_not_called()
    owner.gesture_handler.click_element_at.assert_not_called()


def test_switch_and_click_maps_missing_or_unclickable_elements_to_caller_error():
    owner = make_owner()
    owner.element_finder.wait_for_element_clickable.return_value = None

    result = UIActions(owner).switch_and_click("confirm", error_message="Could not confirm")

    assert result == {"error": "Could not confirm"}
    owner.gesture_handler.click_element_at.assert_not_called()

