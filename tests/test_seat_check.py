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

    @property
    def element_finder(self):
        return self


class DummySeatUI:
    def __init__(self, handler):
        self.handler = handler

    async def expand_and_find_desks(self):
        seat_desks = self.handler.element_finder.find_elements("seat_desk")
        if len(seat_desks) != 6:
            self.handler.log_error(
                f"seat expansion incomplete: found {len(seat_desks)} desks, expected 6"
            )
            return None
        return seat_desks

    def scroll_to_row(self, desk_index, seat_desks, duration=100):
        row_index = desk_index // 2
        if row_index not in (0, 2):
            return
        reference_desk = seat_desks[2]
        center_x = reference_desk.location["x"] + reference_desk.size["width"] // 2
        center_y = reference_desk.location["y"] + reference_desk.size["height"] // 2
        offset = reference_desk.size["height"] if row_index == 0 else -reference_desk.size["height"]
        self.handler.driver.swipe(center_x, center_y, center_x, center_y + offset, duration)


def _desk():
    return SimpleNamespace(
        size={"height": 10, "width": 10},
        location={"x": 0, "y": 0},
    )


def _manager(handler):
    SeatCheckManager._instance = None
    SeatCheckManager._initialized = False
    return SeatCheckManager(handler, DummySeatUI(handler))


def test_check_user_specific_seat_stops_when_expansion_shows_four_desks():
    handler = DummyHandler([_desk() for _ in range(4)])
    manager = _manager(handler)
    asyncio.run(manager.check_user_specific_seat("Chainer", 9))

    assert handler.searched_desks == []
    assert handler.errors == ["seat expansion incomplete: found 4 desks, expected 6"]


def test_check_user_specific_seat_uses_global_index_when_all_desks_are_visible(monkeypatch):
    seat_desks = [_desk() for _ in range(6)]
    handler = DummyHandler(seat_desks)
    manager = _manager(handler)
    sleep = AsyncMock()
    monkeypatch.setattr(seat_check_module.asyncio, "sleep", sleep)
    asyncio.run(manager.check_user_specific_seat("Chainer", 9))

    assert handler.swipes == [(5, 5, 5, -5, 1000)]
    assert handler.searched_desks == [seat_desks[4]]
    sleep.assert_awaited_once_with(0.5)
