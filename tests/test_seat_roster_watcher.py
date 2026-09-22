"""Ticket #307: passive detection, debounce and seat change domain events."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.seat_panel import FakeSeatPanel

from ushareiplay.managers.seat_manager import domain_events
from ushareiplay.managers.seat_manager.domain_events import UserSeatedEvent
from ushareiplay.managers.seat_manager.probe import SeatProbe
from ushareiplay.managers.seat_manager.roster import SeatRoster
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.watcher import SeatRosterWatcher
from ushareiplay.state.room_state import RoomState

#: Short enough to keep the suite fast; the debounce assertions below only need
#: the window to be longer than the gaps between signals.
DEBOUNCE = 0.02
#: Only the test that measures the window itself needs a clock-scale value.
DEBOUNCE_TIMING = 0.2


def _mask(occupied_seats):
    return tuple(seat in occupied_seats for seat in range(1, 13))


class RecordingObs:
    """Stands in for Observability: the production sink for domain events."""

    def __init__(self):
        self.events = []

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs.get("ctx")))


@pytest.fixture(autouse=True)
def _instant_panel_animation(monkeypatch):
    monkeypatch.setattr(SeatUIManager, "EXPANSION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(SeatUIManager, "COLLAPSE_SETTLE_SECONDS", 0)


@pytest.fixture(autouse=True)
def _host_room():
    if not RoomState.is_initialized():
        RoomState.initialize()
    room_state = RoomState.instance()
    room_state.is_guest_room = False
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    return room_state


def _stack(panel, *, busy=None, debounce=DEBOUNCE):
    """``busy=None`` leaves the production busy predicate in place.

    Events are observed through the production sink: a recording runtime on the
    handler's controller, wired exactly as the controller wires it.
    """
    obs = RecordingObs()
    panel.handler.controller = SimpleNamespace(obs=obs)
    roster = SeatRoster()
    ui = SeatUIManager(panel.handler)
    probe = SeatProbe(panel.handler, ui, roster, focus_count_provider=lambda: None)
    ui.bind_probe(probe)
    watcher = SeatRosterWatcher(
        panel.handler,
        ui,
        probe,
        debounce_seconds=debounce,
        is_busy=None if busy is None else (lambda: busy),
    )
    return ui, probe, roster, watcher, obs


async def test_a_focus_count_change_arms_one_probe():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    assert watcher.note_focus_count(1) is True
    await watcher.drain()

    assert panel.expand_clicks == 1


async def test_an_unchanged_focus_count_does_not_arm_a_probe():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    assert watcher.note_focus_count(1) is True
    assert watcher.note_focus_count(1) is False
    await watcher.drain()

    assert panel.expand_clicks == 1


async def test_an_occupancy_mask_change_arms_a_probe():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    assert watcher.note_occupancy_mask([False] * 12) is True
    assert watcher.note_occupancy_mask([True] + [False] * 11) is True
    await watcher.drain()

    assert panel.expand_clicks == 1


async def test_a_repeated_occupancy_mask_does_not_arm_a_probe():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    watcher.note_occupancy_mask([False] * 12)

    assert watcher.note_occupancy_mask([False] * 12) is False


async def test_rapid_focus_count_changes_debounce_into_a_single_probe():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel, debounce=DEBOUNCE_TIMING)

    watcher.note_focus_count(1)
    await asyncio.sleep(DEBOUNCE_TIMING * 0.6)
    # A second change inside the window restarts it rather than probing now.
    watcher.note_focus_count(2)
    await asyncio.sleep(DEBOUNCE_TIMING * 0.6)
    # Past the deadline the first signal set, but not the deadline it was
    # pushed back to.
    still_suppressed = panel.expand_clicks == 0

    await watcher.drain()

    assert still_suppressed is True
    assert panel.expand_clicks == 1


async def test_probing_is_skipped_in_a_guest_room(_host_room):
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)
    _host_room.is_guest_room = True

    watcher.note_focus_count(1)
    await watcher.drain()

    assert panel.expand_clicks == 0


async def test_probing_is_skipped_while_chat_commands_are_queued():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel, busy=True)

    watcher.note_focus_count(1)
    await watcher.drain()

    assert panel.expand_clicks == 0


async def test_probing_yields_while_a_command_owns_the_screen():
    panel = FakeSeatPanel({1: "Alice"})
    ui_lock = asyncio.Lock()
    await ui_lock.acquire()
    _ui, _probe, _roster, watcher, _obs = _stack(panel)
    panel.handler.controller.event_runtime_context = SimpleNamespace(
        is_ui_busy=ui_lock.locked
    )

    watcher.note_focus_count(1)
    await watcher.drain()

    assert panel.expand_clicks == 0


async def test_the_seat_panel_is_collapsed_once_probing_finishes():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    watcher.note_focus_count(1)
    await watcher.drain()

    assert panel.seats_expanded is False
    assert panel.collapse_clicks == 1


async def test_the_panel_is_collapsed_even_when_expansion_yields_no_desks():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)
    panel.handler.element_finder.find_elements = lambda _key: []

    watcher.note_focus_count(1)
    await watcher.drain()

    assert panel.collapse_clicks == 1


async def test_a_new_occupant_emits_a_seated_event():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    watcher.note_focus_count(1)
    await watcher.drain()

    assert obs.events == [
        ("UserSeatedEvent", {"username": "Alice", "seat_number": 1})
    ]


async def test_a_departure_emits_an_unseated_event():
    panel = FakeSeatPanel({1: "Alice", 3: "Bob"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    watcher.note_focus_count(2)
    await watcher.drain()
    obs.events.clear()

    panel.clear_seat(3)
    watcher.note_focus_count(1)
    await watcher.drain()

    assert obs.events == [
        ("UserUnseatedEvent", {"username": "Bob", "seat_number": 3})
    ]


async def test_a_move_emits_a_seat_changed_event():
    panel = FakeSeatPanel({3: "Alice"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    # A seat swap keeps the room's head count identical, so the visible
    # occupancy mask is what has to give it away.
    watcher.note_occupancy_mask(_mask({3}))
    await watcher.drain()
    obs.events.clear()

    panel.clear_seat(3)
    panel.set_occupant(9, "Alice")
    watcher.note_occupancy_mask(_mask({9}))
    await watcher.drain()

    assert obs.events == [
        ("UserSeatChangedEvent", {"username": "Alice", "old_seat": 3, "new_seat": 9})
    ]


async def test_no_events_are_emitted_when_a_signal_was_a_false_alarm():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    watcher.note_occupancy_mask(_mask({1}))
    await watcher.drain()
    obs.events.clear()

    # A flapping signal arms another probe, but nothing actually moved.
    watcher.note_occupancy_mask(_mask({2}))
    await watcher.drain()

    assert obs.events == []


async def test_an_unknown_identity_is_not_reported_as_a_seat_change():
    panel = FakeSeatPanel({1: "Alice"}, popup_failures=[1])
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    watcher.note_focus_count(1)
    await watcher.drain()

    assert obs.events == []


async def test_the_published_event_name_matches_the_domain_event_type():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    watcher.note_focus_count(1)
    await watcher.drain()

    # The published name and payload must be enough to rebuild the event, so a
    # subscriber can recover the typed event from the wire format.
    name, payload = obs.events[0]
    rebuilt = getattr(domain_events, name)(**payload)

    assert rebuilt == UserSeatedEvent("Alice", 1)


async def test_close_cancels_a_probe_that_is_still_debouncing():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    watcher.note_focus_count(1)
    await watcher.close()
    await asyncio.sleep(DEBOUNCE * 1.5)

    assert panel.expand_clicks == 0


async def test_a_failing_probe_never_escapes_the_background_task():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    async def boom():
        raise RuntimeError("seat panel is gone")

    watcher.probe_now = boom

    watcher.note_focus_count(1)
    await watcher.drain()

    assert panel.handler.errors != []
