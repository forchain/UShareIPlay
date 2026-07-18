from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.handlers.soul_handler import SoulHandler
from ushareiplay.managers.recovery_manager import RecoveryManager


@pytest.fixture(autouse=True)
def reset_recovery_manager_singleton():
    RecoveryManager.reset_instance()
    yield
    RecoveryManager.reset_instance()


class FakeHandler:
    def __init__(self, close_after_clicks):
        self.logger = MagicMock()
        self.clicks = 0
        self.close_after_clicks = close_after_clicks
        self.drawer_element = SimpleNamespace(is_displayed=lambda: True)
        self.room_element = object()
        self.press_back = MagicMock()
        self.element_finder = SimpleNamespace(
            wait_for_element_clickable=self.wait_for_element_clickable,
            try_find_element=self.try_find_element,
            wait_for_element=self.wait_for_element,
        )
        self.key_actions = SimpleNamespace(press_back=self.press_back)
        self.ui_actions = SimpleNamespace(perform_click=self.click_element_at)
        self.gesture_handler = SimpleNamespace(click_element_at=self.click_element_at)

    def wait_for_element_clickable(self, key):
        if key == "input_drawer" and self.clicks >= self.close_after_clicks:
            return None
        return self.drawer_element

    def click_element_at(self, element, x_ratio=0.5, y_ratio=0.5, x_offset=0, y_offset=0):
        self.clicks += 1
        return True

    def try_find_element(self, key, log=False):
        if key == "input_drawer" and self.clicks < self.close_after_clicks:
            return self.drawer_element
        return None

    def wait_for_element(self, key):
        if key == "room_id":
            return self.room_element
        return None


def _make_manager(monkeypatch, handler):
    monkeypatch.setattr(SoulHandler, "instance", classmethod(lambda cls: handler))
    return RecoveryManager.initialize()


def test_close_drawer_succeeds_after_second_tap(monkeypatch):
    handler = FakeHandler(close_after_clicks=2)
    manager = _make_manager(monkeypatch, handler)

    assert manager.close_drawer("input_drawer") is True
    assert handler.clicks == 2
    handler.key_actions.press_back.assert_not_called()


def test_close_drawer_does_not_treat_room_id_as_success_when_drawer_remains(monkeypatch):
    handler = FakeHandler(close_after_clicks=3)
    manager = _make_manager(monkeypatch, handler)

    assert manager.close_drawer("input_drawer") is False
    assert handler.clicks == 2
    handler.key_actions.press_back.assert_not_called()


def test_close_drawer_succeeds_after_first_tap(monkeypatch):
    handler = FakeHandler(close_after_clicks=1)
    manager = _make_manager(monkeypatch, handler)

    assert manager.close_drawer("input_drawer") is True
    assert handler.clicks == 1
