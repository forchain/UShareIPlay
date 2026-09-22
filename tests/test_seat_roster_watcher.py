"""Ticket #307: passive detection, debounce and seat change domain events."""

import asyncio
import contextlib
import time
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


def _trigger_probe(watcher):
    watcher.note_occupancy_mask([False] * 12)
    watcher.note_occupancy_mask([True] + [False] * 11)


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


async def test_probe_roster_full_scan_finds_offscreen_occupants():
    # User reported: focus count was 5, but off-screen seats (desks 2-6) were missed.
    # A full scan must check every row and identify off-screen occupants.
    panel = FakeSeatPanel(
        {1: "Chainer", 5: "User2", 7: "User3", 9: "User4", 11: "User5"}
    )
    _ui, _probe, roster, watcher, obs = _stack(panel)

    assert watcher.note_focus_count(5) is True
    await watcher.drain()

    assert panel.expand_clicks == 1
    assert panel.seats_expanded is False
    assert roster.find_seat_of("Chainer") == 1
    assert roster.find_seat_of("User2") == 5
    assert roster.find_seat_of("User3") == 7
    assert roster.find_seat_of("User4") == 9
    assert roster.find_seat_of("User5") == 11
    assert len(roster.occupants()) == 5


async def test_an_occupancy_mask_change_arms_a_probe():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    assert watcher.note_occupancy_mask([False] * 12) is False
    assert watcher.note_occupancy_mask([True] + [False] * 11) is True
    await watcher.drain()

    assert panel.expand_clicks == 1


async def test_a_repeated_occupancy_mask_does_not_arm_a_probe():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    watcher.note_occupancy_mask([False] * 12)

    assert watcher.note_occupancy_mask([False] * 12) is False


async def test_rapid_occupancy_mask_changes_debounce_into_a_single_probe():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel, debounce=DEBOUNCE_TIMING)

    watcher.note_occupancy_mask([False] * 12)
    watcher.note_occupancy_mask([True] + [False] * 11)
    await asyncio.sleep(DEBOUNCE_TIMING * 0.6)
    watcher.note_occupancy_mask([True, True] + [False] * 10)
    await asyncio.sleep(DEBOUNCE_TIMING * 0.6)
    still_suppressed = panel.expand_clicks == 0

    await watcher.drain()

    assert still_suppressed is True
    assert panel.expand_clicks == 1


async def test_probing_is_skipped_in_a_guest_room(_host_room):
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)
    _host_room.is_guest_room = True

    _trigger_probe(watcher)
    await watcher.drain()

    assert panel.expand_clicks == 0


async def test_probing_is_skipped_while_chat_commands_are_queued():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel, busy=True)

    _trigger_probe(watcher)
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

    _trigger_probe(watcher)
    await watcher.drain()

    assert panel.expand_clicks == 0


async def test_probing_holds_the_ui_lock_while_the_panel_is_open():
    panel = FakeSeatPanel({1: "Alice"})
    ui_lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def ui_session(reason):
        async with ui_lock:
            yield

    _ui, _probe, _roster, watcher, _obs = _stack(panel)
    panel.handler.controller.ui_session = ui_session

    lock_held_while_reading = []
    find_elements = panel.handler.element_finder.find_elements

    def record_lock(key):
        lock_held_while_reading.append(ui_lock.locked())
        return find_elements(key)

    panel.handler.element_finder.find_elements = record_lock

    _trigger_probe(watcher)
    await watcher.drain()

    # The panel read happens inside the session, and the probe lets it go again.
    assert lock_held_while_reading == [True]
    assert ui_lock.locked() is False


async def test_the_seat_panel_is_collapsed_once_probing_finishes():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    _trigger_probe(watcher)
    await watcher.drain()

    assert panel.seats_expanded is False
    assert panel.collapse_clicks == 1


async def test_the_panel_is_collapsed_even_when_expansion_yields_no_desks():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)
    panel.handler.element_finder.find_elements = lambda _key: []

    _trigger_probe(watcher)
    await watcher.drain()

    assert panel.collapse_clicks == 1


async def test_a_new_occupant_emits_a_seated_event():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    _trigger_probe(watcher)
    await watcher.drain()

    assert obs.events == [
        ("UserSeatedEvent", {"username": "Alice", "seat_number": 1})
    ]


async def test_a_departure_emits_an_unseated_event():
    panel = FakeSeatPanel({1: "Alice", 3: "Bob"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    watcher.note_occupancy_mask([False] * 12)
    watcher.note_occupancy_mask(_mask({1, 3}))
    await watcher.drain()
    obs.events.clear()

    panel.clear_seat(3)
    watcher.note_occupancy_mask(_mask({1}))
    await watcher.drain()

    assert obs.events == [
        ("UserUnseatedEvent", {"username": "Bob", "seat_number": 3})
    ]


async def test_a_move_emits_a_seat_changed_event():
    panel = FakeSeatPanel({3: "Alice"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    # A seat swap keeps the room's head count identical, so the visible
    # occupancy mask is what has to give it away.
    watcher.note_occupancy_mask([False] * 12)
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

    watcher.note_occupancy_mask([False] * 12)
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

    _trigger_probe(watcher)
    await watcher.drain()

    assert obs.events == []


async def test_the_published_event_name_matches_the_domain_event_type():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, obs = _stack(panel)

    _trigger_probe(watcher)
    await watcher.drain()

    # The published name and payload must be enough to rebuild the event, so a
    # subscriber can recover the typed event from the wire format.
    name, payload = obs.events[0]
    rebuilt = getattr(domain_events, name)(**payload)

    assert rebuilt == UserSeatedEvent("Alice", 1)


async def test_close_cancels_a_probe_that_is_still_debouncing():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    _trigger_probe(watcher)
    await watcher.close()
    await asyncio.sleep(DEBOUNCE * 1.5)

    assert panel.expand_clicks == 0


async def test_close_returns_without_waiting_out_the_debounce_window():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel, debounce=5.0)

    _trigger_probe(watcher)
    started = time.monotonic()
    await watcher.close()
    elapsed = time.monotonic() - started

    # Shutdown must not sit through the window the signal opened.
    assert elapsed < 1.0
    assert panel.expand_clicks == 0


async def test_a_failing_probe_never_escapes_the_background_task():
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    async def boom():
        raise RuntimeError("seat panel is gone")

    watcher.probe_now = boom

    _trigger_probe(watcher)
    await watcher.drain()

    assert panel.handler.errors != []


async def test_collapsed_seats_seamless_monitoring_without_expansion():
    """Collapsed viewport (e.g. double-row / 上下排) monitors seats without expanding."""
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    collapsed_mask = (True, False, False, False) + (None,) * 8
    # Initial baseline sets state without expanding
    assert watcher.note_occupancy_mask(collapsed_mask) is False
    await watcher.drain()
    assert panel.expand_clicks == 0

    # Repeated identical readings remain completely seamless (无感)
    for _ in range(5):
        assert watcher.note_occupancy_mask(collapsed_mask) is False
    await watcher.drain()
    assert panel.expand_clicks == 0


async def test_collapsed_seats_occupancy_change_arms_probe():
    """In collapsed view, detecting a change in seat occupancy arms a probe."""
    panel = FakeSeatPanel({1: "Alice"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    collapsed_mask = (True, False, False, False) + (None,) * 8
    watcher.note_occupancy_mask(collapsed_mask)

    # Bob sits on seat 2 (index 1)
    panel.set_occupant(2, "Bob")
    new_mask = (True, True, False, False) + (None,) * 8
    assert watcher.note_occupancy_mask(new_mask) is True
    await watcher.drain()

    assert panel.expand_clicks == 1
    assert panel.seats_expanded is False  # collapsed after probe


async def test_post_probe_collapse_does_not_loop():
    """After a probe completes and collapses, collapsed viewport does not re-arm."""
    panel = FakeSeatPanel({1: "Alice", 2: "Bob", 5: "Charlie"})
    _ui, _probe, _roster, watcher, _obs = _stack(panel)

    # Baseline
    watcher.note_occupancy_mask((True, False, False, False) + (None,) * 8)

    # Seat 2 taken -> probe fires, discovers Charlie on seat 5 too
    assert watcher.note_occupancy_mask((True, True, False, False) + (None,) * 8) is True
    await watcher.drain()
    assert panel.expand_clicks == 1
    assert panel.seats_expanded is False

    # Back in collapsed state, only seats 1-4 are visible again (seat 5 is None)
    # Must NOT treat seat 5 being None as a departure or change!
    assert watcher.note_occupancy_mask((True, True, False, False) + (None,) * 8) is False
    await watcher.drain()
    assert panel.expand_clicks == 1  # Still 1, did not loop!
