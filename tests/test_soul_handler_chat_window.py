"""Tests for ensuring SoulHandler chat window is closed after input / sending messages."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.handlers.soul_handler import SoulHandler


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


class _FakeElement:
    def __init__(self, events, name, displayed=True):
        self.events = events
        self.name = name
        self._displayed = displayed
        self.size = {"width": 200, "height": 80}
        self.location = {"x": 50, "y": 600}

    def click(self):
        self.events.append(f"click:{self.name}")

    def send_keys(self, text):
        self.events.append(f"send_keys:{self.name}:{text}")

    def is_displayed(self):
        return self._displayed


class _FakeElementFinder:
    def __init__(self, events, chat_open=False, disappear_on_click=True, disappear_on_back=True):
        self.events = events
        self.chat_open = chat_open
        self.disappear_on_click = disappear_on_click
        self.disappear_on_back = disappear_on_back
        self.disappear_calls = []

        self._input_box_entry = _FakeElement(events, "input_box_entry")
        self._input_box = _FakeElement(events, "input_box")
        self._button_send = _FakeElement(events, "button_send")
        self.missing_send_button = False

    def try_find_element(self, key, log=False, clickable=False):
        if key == "input_box" and self.chat_open:
            return self._input_box
        if key == "go_back_1":
            return None
        return None

    def wait_for_element_clickable(self, key, timeout=None):
        if key == "input_box_entry":
            return self._input_box_entry
        if key == "input_box":
            self.chat_open = True
            return self._input_box
        if key == "button_send":
            if self.missing_send_button:
                return None
            return self._button_send
        return None

    def wait_for_element_disappear(self, key, timeout=1.0, poll_frequency=0.1):
        self.disappear_calls.append((key, timeout))
        if key == "input_box":
            return not self.chat_open
        return True


class _FakeGestureHandler:
    def __init__(self, events, finder):
        self.events = events
        self.finder = finder

    def click_element_at(self, element, x_ratio=0.5, y_ratio=0.5, x_offset=0, y_offset=0):
        self.events.append(
            f"click_element_at:{element.name}:x_ratio={x_ratio}:y_ratio={y_ratio}:x_offset={x_offset}:y_offset={y_offset}"
        )
        if self.finder.disappear_on_click:
            self.finder.chat_open = False
        return True


class _FakeKeyActions:
    def __init__(self, events, finder):
        self.events = events
        self.finder = finder

    def switch_to_app(self):
        self.events.append("switch_to_app")
        return True

    def press_back(self):
        self.events.append("press_back")
        if self.finder.disappear_on_back:
            self.finder.chat_open = False
        return True


def _make_handler(events, **kwargs):
    handler = SoulHandler.__new__(SoulHandler)
    handler.logger = _Logger()
    finder = _FakeElementFinder(events, **kwargs)
    handler.element_finder = finder
    handler.gesture_handler = _FakeGestureHandler(events, finder)
    handler.key_actions = _FakeKeyActions(events, finder)
    return handler, finder


def test_is_chat_window_open_when_not_found():
    events = []
    handler, _ = _make_handler(events, chat_open=False)
    assert handler.is_chat_window_open() is False


def test_is_chat_window_open_when_displayed():
    events = []
    handler, _ = _make_handler(events, chat_open=True)
    assert handler.is_chat_window_open() is True


def test_is_chat_window_open_when_hidden():
    events = []
    handler, finder = _make_handler(events, chat_open=True)
    finder._input_box._displayed = False
    assert handler.is_chat_window_open() is False


def test_ensure_chat_window_closed_noop_when_already_closed():
    events = []
    handler, _ = _make_handler(events, chat_open=False)
    assert handler.ensure_chat_window_closed() is True
    assert "click_element_at" not in str(events)
    assert "press_back" not in events


def test_ensure_chat_window_closed_via_click_outside():
    events = []
    handler, _ = _make_handler(events, chat_open=True, disappear_on_click=True)
    assert handler.ensure_chat_window_closed() is True
    assert any("click_element_at:input_box" in ev for ev in events)
    assert "press_back" not in events
    assert handler.is_chat_window_open() is False


def test_ensure_chat_window_closed_fallback_press_back():
    events = []
    handler, _ = _make_handler(events, chat_open=True, disappear_on_click=False, disappear_on_back=True)
    assert handler.ensure_chat_window_closed() is True
    assert any("click_element_at:input_box" in ev for ev in events)
    assert "press_back" in events
    assert handler.is_chat_window_open() is False


def test_send_message_ensures_closed_on_success():
    events = []
    handler, _ = _make_handler(events, chat_open=False, disappear_on_click=True)
    result = handler.send_message("hello world")
    assert result is None or not (isinstance(result, dict) and "error" in result)
    assert "click:input_box_entry" in events
    assert "send_keys:input_box:hello world" in events
    assert "click:button_send" in events
    assert any("click_element_at:input_box" in ev for ev in events)
    assert handler.is_chat_window_open() is False


def test_send_message_empty_ensures_closed():
    events = []
    handler, _ = _make_handler(events, chat_open=False, disappear_on_click=True)
    result = handler.send_message("")
    assert result is None or not (isinstance(result, dict) and "error" in result)
    assert "click:input_box_entry" in events
    assert "click:button_send" not in events
    assert any("click_element_at:input_box" in ev for ev in events)
    assert handler.is_chat_window_open() is False


def test_send_message_ensures_closed_on_send_button_missing():
    events = []
    handler, finder = _make_handler(events, chat_open=False, disappear_on_click=True)
    finder.missing_send_button = True
    result = handler.send_message("hello")
    assert isinstance(result, dict) and "error" in result
    # Crucial: input_box was opened, button_send was missing, but input_box must STILL be closed!
    assert handler.is_chat_window_open() is False
    assert any("click_element_at:input_box" in ev for ev in events)


def test_send_message_closes_pre_existing_open_chat_window():
    events = []
    handler, finder = _make_handler(events, chat_open=True, disappear_on_click=True)
    result = handler.send_message("clean slate")
    assert result is None or not (isinstance(result, dict) and "error" in result)
    assert handler.is_chat_window_open() is False
