import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ushareiplay.managers.seat_manager import seat_check as seat_check_module
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager


class DummyHandler:
    def __init__(self, desks):
        self.logger = SimpleNamespace(
            info=lambda message: None,
            warning=lambda message: None,
            error=lambda message: None,
        )
        self.desks = desks
        self.searched_desks = []
        self.errors = []
        self.swipes = []
        self.driver = SimpleNamespace(swipe=lambda *args: self.swipes.append(args))

    def find_elements(self, key):
        assert key == "seat_desk"
        return self.desks

    def log_error(self, message):
        self.errors.append(message)

    def send_message(self, message):
        pass

    def find_child_element(self, parent, key):
        if key == "left_seat":
            self.searched_desks.append(parent)
            return object()
        return None


class DummySeatUI:
    async def expand_seats(self):
        return True


def _desk():
    return SimpleNamespace(
        size={"height": 10, "width": 10},
        location={"x": 0, "y": 0},
    )


def _manager(handler):
    SeatCheckManager._instance = None
    SeatCheckManager._initialized = False
    manager = SeatCheckManager(handler)
    manager.seat_ui = DummySeatUI()
    return manager


def test_check_user_specific_seat_stops_when_expansion_shows_four_desks(monkeypatch):
    handler = DummyHandler([_desk() for _ in range(4)])
    manager = _manager(handler)
    monkeypatch.setattr(seat_check_module.asyncio, "sleep", AsyncMock())

    asyncio.run(manager.check_user_specific_seat("Chainer", 9))

    assert handler.searched_desks == []
    assert handler.errors == ["seat expansion incomplete: found 4 desks, expected 6"]


def test_check_user_specific_seat_uses_global_index_when_all_desks_are_visible(monkeypatch):
    seat_desks = [_desk() for _ in range(6)]
    handler = DummyHandler(seat_desks)
    manager = _manager(handler)
    monkeypatch.setattr(seat_check_module.asyncio, "sleep", AsyncMock())

    asyncio.run(manager.check_user_specific_seat("Chainer", 9))

    assert handler.swipes == [(5, 5, 5, -5, 1000)]
    assert handler.searched_desks == [seat_desks[4]]
