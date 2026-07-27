import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.reservation import ReservationManager
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager


class _FakeSeatUI:
    def __init__(self, expanded):
        self.expanded = expanded
        self.collapsed = False

    def check_seats_state(self):
        return self.expanded

    async def collapse_seats(self):
        self.collapsed = True
        return True


class _FakeReservation:
    async def reserve_seat(self, username, seat_number):
        return {"reserved": (username, seat_number)}


class _FakeSeating:
    async def sit_at_specific_seat(self, seat_number):
        return {"took": seat_number}

    async def seat_off_owner(self):
        return {"removed": "owner"}

    async def seat_off_specific_seat(self, seat_number):
        return {"removed": seat_number}


def _manager_with_fakes(ui=None, reservation=None, seating=None):
    manager = object.__new__(SeatManager)
    manager._ui = ui or _FakeSeatUI(expanded=False)
    manager._reservation = reservation or _FakeReservation()
    manager._seating = seating or _FakeSeating()
    return manager


@pytest.mark.asyncio
async def test_prepare_for_chat_scan_collapses_only_when_seats_are_expanded():
    expanded_ui = _FakeSeatUI(expanded=True)
    collapsed_ui = _FakeSeatUI(expanded=False)

    assert await _manager_with_fakes(ui=expanded_ui).prepare_for_chat_scan() is True
    assert expanded_ui.collapsed is True

    assert await _manager_with_fakes(ui=collapsed_ui).prepare_for_chat_scan() is True
    assert collapsed_ui.collapsed is False


@pytest.mark.asyncio
async def test_seat_management_delegates_reserve_and_take_intentions():
    manager = _manager_with_fakes()

    assert await manager.reserve_seat("Alice", 5) == {"reserved": ("Alice", 5)}
    assert await manager.take_seat(7) == {"took": 7}


@pytest.mark.asyncio
async def test_seat_management_preserves_remove_occupant_paths():
    manager = _manager_with_fakes()

    assert await manager.remove_seat_occupant(None) == {"removed": "owner"}
    assert await manager.remove_seat_occupant(3) == {"removed": 3}


def test_seat_management_shares_ui_and_check_dependencies():
    singleton_classes = (SeatManager,)
    for manager_class in singleton_classes:
        manager_class._instance = None
        manager_class._initialized = False

    handler = object()
    manager = SeatManager.get_instance(handler)

    assert manager._ui is manager._check.seat_ui
    assert manager._ui is manager._reservation.seat_ui
    assert manager._ui is manager._seating.seat_ui
    assert manager._reservation.seat_check is manager._check

    for manager_class in singleton_classes:
        manager_class._instance = None
        manager_class._initialized = False


@pytest.mark.asyncio
async def test_command_execution_recover_missed_history_prepares_chat_scan(monkeypatch):
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSeatManagement:
        def __init__(self):
            self.prepared = False

        async def prepare_for_chat_scan(self):
            self.prepared = True
            return True

    class _FakeGestureHandler:
        def scroll_container_until_element(self, *_args, **_kwargs):
            return None, None, []

        def send_message(self, _message):
            return None

    seat_management = _FakeSeatManagement()
    monkeypatch.setattr(
        MessageManager,
        "_get_seat_manager",
        lambda self: seat_management,
    )
    # Command Execution seam resolves the seat manager through MessageManager.
    # The conftest fixture resets all singletons between tests; ensure
    # MessageManager is initialised for this test and reverted afterwards.
    # Ensure MessageManager singleton exists for the duration of this test.
    # The conftest fixture's teardown will reset all singletons afterwards.
    if not MessageManager.__dict__.get("_singleton_initialized", False):
        MessageManager.initialize()
    monkeypatch.setattr(CommandManager, "instance", classmethod(lambda cls: object.__new__(CommandManager)), raising=False)

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    handler = SimpleNamespace(
        logger=SimpleNamespace(error=lambda message: None, critical=lambda message: None),
    )
    handler.key_actions = SimpleNamespace(switch_to_app=lambda: True)
    handler.gesture_handler = _FakeGestureHandler()
    handler.send_message = lambda _message: None
    manager._handler = handler
    manager._chat_logger = None
    manager._recent_chats = deque(["souler[Anchor]说：:noop"], maxlen=3)
    manager._latest_chats = deque(maxlen=3)

    assert await manager.recover_missed_history() is None
    assert seat_management.prepared is True
