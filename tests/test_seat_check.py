import asyncio
from types import SimpleNamespace

import pytest

from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager


def _reset_seat_check_manager_singleton():
    SeatCheckManager._instance = None
    SeatCheckManager._initialized = False


@pytest.fixture(autouse=True)
def reset_seat_check_manager_singleton():
    _reset_seat_check_manager_singleton()
    yield
    _reset_seat_check_manager_singleton()


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def error(self, message):
        self.messages.append(("error", message))

    def warning(self, message):
        self.messages.append(("warning", message))


class DummyElement:
    def __init__(self, text="", children=None):
        self.text = text
        self.children = children or {}
        self.clicked = False
        self.size = {"height": 10, "width": 10}
        self.location = {"x": 0, "y": 0}

    def click(self):
        self.clicked = True

    def get(self, key):
        return self.children.get(key)


class DummyDesk(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.size = {"height": 10, "width": 10}
        self.location = {"x": 0, "y": 0}


class DummyDriver:
    def __init__(self):
        self.swiped = False

    def swipe(self, *args):
        self.swiped = True


class DummyHandler:
    def __init__(self, initial_desks, scrolled_desks, popup_name):
        self.initial_desks = initial_desks
        self.scrolled_desks = scrolled_desks
        self.popup_name = popup_name
        self.logger = DummyLogger()
        self.driver = DummyDriver()
        self.sent_messages = []
        self.back_pressed = False

    def find_elements(self, key):
        if key != "seat_desk":
            return []
        return self.scrolled_desks if self.driver.swiped else self.initial_desks

    def find_child_element(self, desk, key, log_failure=True):
        return desk.get(key)

    def wait_for_element_clickable(self, key):
        if key == "seat_off":
            return DummyElement("抱下")
        return None

    def wait_for_any_element(self, keys):
        return keys[0], DummyElement(self.popup_name)

    def send_message(self, message):
        self.sent_messages.append(message)

    def press_back(self):
        self.back_pressed = True

    def log_error(self, message):
        self.logger.error(message)


class DummySeatUI:
    async def expand_seats(self):
        return True


def _desk(left_label="", left_occupied=False, right_label="", right_occupied=False):
    left_label_element = DummyElement(left_label) if left_label else None
    right_label_element = DummyElement(right_label) if right_label else None
    return DummyDesk({
        "left_seat": DummyElement(children={"left_label": left_label_element}),
        "right_seat": DummyElement(children={"right_label": right_label_element}),
        "left_state": DummyElement() if left_occupied else None,
        "right_state": DummyElement() if right_occupied else None,
        "left_label": left_label_element,
        "right_label": right_label_element,
    })


def test_check_user_specific_seat_refreshes_desks_after_scrolling_to_third_row(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("ushareiplay.managers.seat_manager.seat_check.asyncio.sleep", no_sleep)

    initial_desks = [
        _desk(left_label="A", left_occupied=True),
        _desk(left_label="B", left_occupied=True),
        _desk(left_label="C", left_occupied=True),
        _desk(left_label="D", left_occupied=True),
    ]
    scrolled_desks = [
        _desk(left_label="C", left_occupied=True),
        _desk(left_label="D", left_occupied=True),
        _desk(right_label="Occupied", right_occupied=True),
        _desk(left_label="F", left_occupied=True),
    ]
    handler = DummyHandler(initial_desks, scrolled_desks, popup_name="Alice")
    manager = SeatCheckManager(handler)
    manager.seat_ui = DummySeatUI()

    asyncio.run(manager.check_user_specific_seat("Alice", 10))

    assert handler.driver.swiped is True
    assert scrolled_desks[2]["right_seat"].clicked is True
    assert handler.back_pressed is True
