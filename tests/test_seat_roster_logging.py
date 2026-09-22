"""Ticket #310: highlighted Seat Roster logs on probing updates and self-actions."""

import asyncio
import re
from types import SimpleNamespace

import pytest

from tests.seat_panel import make_panel

from ushareiplay.core.roles import DEFAULT_ROOM_OWNER
from ushareiplay.managers.seat_manager.probe import SeatProbe
from ushareiplay.managers.seat_manager.roster import SeatRoster
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.state.room_state import RoomState

_ANSI = re.compile(r"\033\[[0-9;]*m")


@pytest.fixture(autouse=True)
def _instant_panel_animation(monkeypatch):
    """The panel animation pause is real time; tests do not need to wait for it."""
    monkeypatch.setattr(SeatUIManager, "EXPANSION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(SeatUIManager, "COLLAPSE_SETTLE_SECONDS", 0)


@pytest.fixture(autouse=True)
def _host_room():
    """RoomState is a singleton; make sure the guard reads as "our own room"."""
    if not RoomState.is_initialized():
        RoomState.initialize()
    room_state = RoomState.instance()
    room_state.is_guest_room = False
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    yield room_state


def _plain(message):
    """A log record without its highlighting, so its text can be asserted on."""
    return _ANSI.sub("", message)


def _roster_logs(panel):
    """Log records that rendered a roster table, oldest first."""
    return [
        message
        for level, message in panel.handler.logger.records
        if level == "info" and "Seat Roster ·" in message
    ]


def _change_rows(message):
    """The transition summary of one logged roster, as token lists."""
    return [line.strip("│ ").split() for line in message.splitlines() if "➔" in line]


def _all_change_rows(panel):
    return [
        row for message in _roster_logs(panel) for row in _change_rows(_plain(message))
    ]


def _stack(panel, focus_count=None):
    roster = SeatRoster()
    ui = SeatUIManager(panel.handler)
    probe = SeatProbe(
        panel.handler, ui, roster, focus_count_provider=lambda: focus_count
    )
    ui.bind_probe(probe)
    seating = SeatingManager(panel.handler, ui, probe=probe)
    return ui, probe, roster, seating


def _synced(panel, focus_count=None):
    """Reconcile once so the roster starts consistent with the panel."""
    _ui, probe, roster, _seating = _stack(panel, focus_count)
    asyncio.run(probe.sync(panel.desks, focus_count=focus_count))
    panel.handler.logger.records.clear()
    return probe, roster


def _primed(panel):
    """Expand the panel once so the roster starts consistent with it."""
    ui, probe, roster, seating = _stack(panel)
    asyncio.run(ui.expand_and_find_desks())
    panel.handler.logger.records.clear()
    return ui, probe, roster, seating


def test_probe_sync_logs_the_roster_when_an_occupant_arrives():
    panel, _desks = make_panel({1: "Alice"})
    probe, _roster = _synced(panel, focus_count=1)

    panel.set_occupant(5, "Bob")
    asyncio.run(probe.sync(panel.desks, focus_count=2))

    logs = _roster_logs(panel)
    assert len(logs) == 1
    assert ["入座", "Bob", "空", "➔", "5"] in _change_rows(_plain(logs[0]))
    assert "5 Bob" in _plain(logs[0])


def test_probe_sync_logs_the_roster_when_an_occupant_departs():
    panel, _desks = make_panel({1: "Alice", 5: "Bob"})
    probe, _roster = _synced(panel, focus_count=2)

    panel.clear_seat(5)
    asyncio.run(probe.sync(panel.desks, focus_count=1))

    logs = _roster_logs(panel)
    assert len(logs) == 1
    assert ["离座", "Bob", "5", "➔", "空"] in _change_rows(_plain(logs[0]))


def test_probe_sync_logs_when_an_unidentified_occupant_leaves():
    panel, _desks = make_panel({1: "Alice"}, popup_failures={1})
    probe, _roster = _synced(panel, focus_count=1)

    panel.clear_seat(1)
    result = asyncio.run(probe.sync(panel.desks, focus_count=0))

    assert result.cleared_seats == [1]
    assert result.changes == []
    assert len(_roster_logs(panel)) == 1


def test_probe_sync_logs_nothing_when_no_seat_moved():
    panel, _desks = make_panel({1: "Alice", 5: "Bob"})
    probe, _roster = _synced(panel, focus_count=2)

    asyncio.run(probe.sync(panel.desks, focus_count=2))

    assert _roster_logs(panel) == []


def test_probe_sync_logs_a_swap_as_two_movements():
    panel, _desks = make_panel({1: "Alice", 2: "Bob"})
    probe, roster = _synced(panel, focus_count=2)

    panel.set_occupant(1, "Bob")
    panel.set_occupant(2, "Alice")
    roster.invalidate(1)
    roster.invalidate(2)
    asyncio.run(probe.sync(panel.desks, focus_count=2))

    logs = _roster_logs(panel)
    assert len(logs) == 1
    assert ["换位", "Alice", "1", "➔", "2"] in _change_rows(_plain(logs[0]))
    assert ["换位", "Bob", "2", "➔", "1"] in _change_rows(_plain(logs[0]))


def test_the_logged_roster_is_highlighted():
    panel, _desks = make_panel({1: "Alice"})
    probe, _roster = _synced(panel, focus_count=1)

    panel.set_occupant(5, "Bob")
    asyncio.run(probe.sync(panel.desks, focus_count=2))

    log = _roster_logs(panel)[0]
    assert "\033[32mBob\033[0m" in log
    assert "\033[36m│" in log


def test_expanding_for_a_seat_command_logs_the_roster_change():
    panel, _desks = make_panel({2: "Alice"})
    _ui, _probe, _roster, seating = _primed(panel)

    panel.set_occupant(5, "Bob")
    asyncio.run(seating.sit_at_specific_seat(1))

    assert ["入座", "Bob", "空", "➔", "5"] in _all_change_rows(panel)


def test_taking_a_seat_logs_the_self_seated_movement():
    panel, _desks = make_panel({})
    _ui, _probe, _roster, seating = _primed(panel)

    asyncio.run(seating.sit_at_specific_seat(3))

    logs = _roster_logs(panel)
    assert len(logs) == 1
    assert ["入座", DEFAULT_ROOM_OWNER, "空", "➔", "3"] in _change_rows(_plain(logs[0]))


def test_moving_to_another_seat_logs_the_self_move():
    panel, _desks = make_panel({1: DEFAULT_ROOM_OWNER}, owner_seats=[1])
    _ui, _probe, _roster, seating = _primed(panel)

    asyncio.run(seating.sit_at_specific_seat(6))

    logs = _roster_logs(panel)
    assert len(logs) == 1
    assert ["换位", DEFAULT_ROOM_OWNER, "1", "➔", "6"] in _change_rows(_plain(logs[0]))


def test_removing_an_occupant_logs_the_unseated_occupant():
    panel, _desks = make_panel({5: "Bob"})
    _ui, _probe, _roster, seating = _primed(panel)

    asyncio.run(seating.seat_off_specific_seat(5))

    logs = _roster_logs(panel)
    assert len(logs) == 1
    assert ["离座", "Bob", "5", "➔", "空"] in _change_rows(_plain(logs[0]))
    assert "5 空" in _plain(logs[0])
