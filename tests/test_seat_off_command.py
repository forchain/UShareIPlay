import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ushareiplay.commands import seat as seat_command_module
from ushareiplay.commands.seat import SeatCommand
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.models.message_info import MessageInfo


def _reset_seating_manager_singleton():
    SeatingManager._instance = None
    SeatingManager._initialized = False


@pytest.fixture(autouse=True)
def reset_seating_manager_singleton():
    _reset_seating_manager_singleton()
    yield
    _reset_seating_manager_singleton()


class DummyController:
    def __init__(self):
        self.soul_handler = SimpleNamespace(log_error=lambda message: None)
        self.music_handler = None


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
    def __init__(self, text=""):
        self.text = text
        self.clicked = False
        self.size = {"height": 10, "width": 10}
        self.location = {"x": 0, "y": 0}

    def click(self):
        self.clicked = True


class DummyHandler:
    def __init__(self, desks, popup_name="Alice", seat_off=None):
        self.desks = desks
        self.popup_name = popup_name
        self.seat_off = seat_off or DummyElement("抱下")
        self.logger = DummyLogger()
        self.driver = SimpleNamespace(swipe=lambda *args, **kwargs: None)
        self.back_pressed = False

    def find_elements(self, key):
        if key == "seat_desk":
            return self.desks
        return []

    def find_child_element(self, desk, key, log_failure=True):
        return desk.get(key)

    def wait_for_element_clickable(self, key):
        if key == "seat_off":
            return self.seat_off
        return None

    def wait_for_any_element(self, keys):
        return keys[0], DummyElement(self.popup_name)

    def press_back(self):
        self.back_pressed = True

    def log_error(self, message):
        self.logger.error(message)


class DummySeatUI:
    async def expand_seats(self):
        return True


def _desk(left_label="", left_occupied=False, right_label="", right_occupied=False):
    return {
        "left_seat": DummyElement(),
        "right_seat": DummyElement(),
        "left_state": DummyElement() if left_occupied else None,
        "right_state": DummyElement() if right_occupied else None,
        "left_label": DummyElement(left_label) if left_label else None,
        "right_label": DummyElement(right_label) if right_label else None,
    }


def test_seat_1_delegates_reservation_to_seat_management(monkeypatch):
    manager = SimpleNamespace(
        reserve_seat=AsyncMock(return_value={"success": "Seat 5 reserved"})
    )
    monkeypatch.setattr(seat_command_module, "seat_manager", manager)

    command = SeatCommand(DummyController())
    message = MessageInfo(content=":seat 1 5", nickname="Alice")

    result = asyncio.run(command.process(message, ["1", "5"]))

    assert result == {"success": "Seat 5 reserved"}
    manager.reserve_seat.assert_awaited_once_with("Alice", 5)


def test_seat_2_delegates_specific_seat_to_seat_management(monkeypatch):
    manager = SimpleNamespace(take_seat=AsyncMock(return_value={"success": "Took seat 5"}))
    monkeypatch.setattr(seat_command_module, "seat_manager", manager)

    command = SeatCommand(DummyController())
    message = MessageInfo(content=":seat 2 5", nickname="Alice")

    result = asyncio.run(command.process(message, ["2", "5"]))

    assert result == {"success": "Took seat 5"}
    manager.take_seat.assert_awaited_once_with(5)


def test_seat_4_without_parameter_dispatches_owner_seat_off(monkeypatch):
    manager = SimpleNamespace(
        remove_seat_occupant=AsyncMock(return_value={"success": "Owner removed from seat"})
    )
    monkeypatch.setattr(seat_command_module, "seat_manager", manager)

    command = SeatCommand(DummyController())
    message = MessageInfo(content=":seat 4", nickname="Alice")

    result = asyncio.run(command.process(message, ["4"]))

    assert result == {"success": "Owner removed from seat"}
    manager.remove_seat_occupant.assert_awaited_once_with(None)


def test_seat_4_with_parameter_dispatches_specific_seat_off(monkeypatch):
    manager = SimpleNamespace(
        remove_seat_occupant=AsyncMock(return_value={"success": "Seat 5 removed"})
    )
    monkeypatch.setattr(seat_command_module, "seat_manager", manager)

    command = SeatCommand(DummyController())
    message = MessageInfo(content=":seat 4 5", nickname="Alice")

    result = asyncio.run(command.process(message, ["4", "5"]))

    assert result == {"success": "Seat 5 removed"}
    manager.remove_seat_occupant.assert_awaited_once_with(5)


def test_seat_4_with_invalid_seat_number_returns_error(monkeypatch):
    manager = SimpleNamespace(remove_seat_occupant=AsyncMock())
    monkeypatch.setattr(seat_command_module, "seat_manager", manager)

    command = SeatCommand(DummyController())
    message = MessageInfo(content=":seat 4 13", nickname="Alice")

    result = asyncio.run(command.process(message, ["4", "13"]))

    assert result == {"error": "Invalid seat number. Must be between 1 and 12"}
    manager.remove_seat_occupant.assert_not_called()


def test_seat_off_owner_clicks_owner_seat_and_seat_off_button():
    desks = [_desk(left_label="群主", left_occupied=True)]
    handler = DummyHandler(desks, popup_name="群主")
    manager = SeatingManager(handler)
    manager.seat_ui = DummySeatUI()

    result = asyncio.run(manager.seat_off_owner())

    assert result == {"success": "Successfully removed 群主 from seat 1"}
    assert desks[0]["left_seat"].clicked is True
    assert handler.seat_off.clicked is True


def test_seat_off_specific_seat_clicks_target_seat_and_seat_off_button():
    desks = [
        _desk(left_label="A", left_occupied=True, right_label="B", right_occupied=True),
        _desk(left_label="C", left_occupied=True),
    ]
    handler = DummyHandler(desks, popup_name="C")
    manager = SeatingManager(handler)
    manager.seat_ui = DummySeatUI()

    result = asyncio.run(manager.seat_off_specific_seat(3))

    assert result == {"success": "Successfully removed C from seat 3"}
    assert desks[1]["left_seat"].clicked is True
    assert handler.seat_off.clicked is True


def test_seat_off_owner_returns_error_when_owner_not_found():
    handler = DummyHandler([_desk(left_label="Alice", left_occupied=True)])
    manager = SeatingManager(handler)
    manager.seat_ui = DummySeatUI()

    result = asyncio.run(manager.seat_off_owner())

    assert result == {"error": "Owner is not on any seat"}
    assert handler.seat_off.clicked is False
