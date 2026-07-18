from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import InvalidElementStateException

from ushareiplay.core.ui.gesture_handler import GestureHandler


class _Owner:
    def __init__(self, driver):
        self.driver = driver
        self.logger = MagicMock()
        self.config = {}


def _make_handler(driver):
    return GestureHandler(_Owner(driver))


def test_click_element_at_uses_mobile_click_gesture():
    driver = MagicMock()
    driver.get_window_size.return_value = {"width": 1080, "height": 2400}
    element = MagicMock()
    element.size = {"width": 200, "height": 80}
    element.location = {"x": 100, "y": 200}

    handler = _make_handler(driver)
    assert handler.click_element_at(element, x_ratio=0.5, y_ratio=0.5) is True

    driver.execute_script.assert_called_once_with(
        "mobile: clickGesture", {"x": 200, "y": 240}
    )


def test_click_element_at_falls_back_to_element_click_when_gestures_fail(monkeypatch):
    driver = MagicMock()
    driver.get_window_size.return_value = {"width": 1080, "height": 2400}
    driver.execute_script.side_effect = InvalidElementStateException("gesture failed")
    element = MagicMock()
    element.size = {"width": 200, "height": 80}
    element.location = {"x": 100, "y": 200}
    element.click.return_value = None

    class _FailingActions:
        def __init__(self, *_args, **_kwargs):
            self.w3c_actions = MagicMock()

        def perform(self):
            raise InvalidElementStateException("w3c failed")

    monkeypatch.setattr(
        "ushareiplay.core.ui.gesture_handler.ActionChains", _FailingActions
    )

    handler = _make_handler(driver)
    assert handler.click_element_at(element) is True
    element.click.assert_called_once_with()


def test_click_element_at_clamps_negative_y_ratio_to_screen_top():
    driver = MagicMock()
    driver.get_window_size.return_value = {"width": 1080, "height": 2400}
    element = MagicMock()
    element.size = {"width": 200, "height": 80}
    element.location = {"x": 100, "y": 40}

    handler = _make_handler(driver)
    assert handler.click_element_at(element, x_ratio=0.5, y_ratio=-1) is True

    driver.execute_script.assert_called_once_with(
        "mobile: clickGesture", {"x": 200, "y": 0}
    )


def test_clamp_click_coords_without_window_size_uses_legacy_floor():
    driver = MagicMock()
    driver.get_window_size.side_effect = RuntimeError("no session")
    handler = _make_handler(driver)

    assert handler._clamp_click_coords(120, -20) == (120, 60)


class FakeLogger:
    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class FakeDriver:
    def __init__(self):
        self.swipes = []

    def swipe(self, start_x, start_y, end_x, end_y, duration_ms):
        self.swipes.append((start_x, start_y, end_x, end_y, duration_ms))
        return None


def test_perform_swipe_uses_driver_swipe():
    driver = FakeDriver()
    handler = GestureHandler(
        SimpleNamespace(driver=driver, logger=FakeLogger(), config={})
    )

    assert handler.swipe(10, 20, 30, 40, duration_ms=250) is True
    assert driver.swipes == [(10, 20, 30, 40, 250)]


def test_scroll_container_uses_deliberate_swipe_duration():
    driver = MagicMock()
    driver.page_source = "<page />"
    handler = _make_handler(driver)
    handler.wait_for_element_clickable = MagicMock(
        return_value=SimpleNamespace(
            location={"x": 0, "y": 0},
            size={"width": 100, "height": 100},
        )
    )
    handler.find_child_element = MagicMock(return_value=None)
    handler._perform_swipe = MagicMock(return_value=False)

    handler.scroll_container_until_element("message_content", "message_list")

    handler._perform_swipe.assert_called_once_with(50, 90, 50, 10, duration_ms=300)
