"""Ticket #305: opportunistic seat sync on panel expansion and post-action mutation."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.seat_panel import make_panel

from ushareiplay.core.roles import DEFAULT_ROOM_OWNER
from ushareiplay.managers.seat_manager.probe import SeatProbe
from ushareiplay.managers.seat_manager.roster import UNKNOWN_USERNAME, SeatRoster
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def _instant_panel_animation(monkeypatch):
    """The panel animation pause is real time; tests do not need to wait for it."""
    monkeypatch.setattr(SeatUIManager, "EXPANSION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(SeatUIManager, "COLLAPSE_SETTLE_SECONDS", 0)


@pytest.fixture
def _host_room():
    """RoomState is a singleton; make sure the guard reads as "our own room"."""
    if not RoomState.is_initialized():
        RoomState.initialize()
    room_state = RoomState.instance()
    room_state.is_guest_room = False
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    yield room_state


def _stack(panel, focus_count=None):
    roster = SeatRoster()
    ui = SeatUIManager(panel.handler)
    probe = SeatProbe(
        panel.handler, ui, roster, focus_count_provider=lambda: focus_count
    )
    ui.bind_probe(probe)
    seating = SeatingManager(panel.handler, ui, probe=probe)
    return ui, probe, roster, seating


def _primed(panel, focus_count=None):
    """Expand once so the roster starts consistent with the visible panel."""
    ui, probe, roster, seating = _stack(panel, focus_count)
    asyncio.run(ui.expand_and_find_desks())
    panel.popup_clicks = 0
    panel.press_backs = 0
    panel.scrolls.clear()
    return ui, probe, roster, seating


def test_first_expansion_populates_the_roster():
    panel, _desks = make_panel({1: "Alice", 3: "Bob"})
    ui, _probe, roster, _seating = _stack(panel)

    asyncio.run(ui.expand_and_find_desks())

    assert panel.popup_clicks == 2
    assert roster.find_seat_of("Alice") == 1
    assert roster.find_seat_of("Bob") == 3


def test_expanding_seats_syncs_a_dirty_roster():
    panel, _desks = make_panel({1: "Alice"})
    ui, _probe, roster, _seating = _primed(panel)

    panel.set_occupant(7, "Carol")

    asyncio.run(ui.expand_and_find_desks())

    assert panel.popup_clicks == 1
    assert roster.find_seat_of("Carol") == 7


def test_expanding_seats_skips_probing_when_the_roster_is_clean():
    panel, _desks = make_panel({1: "Alice", 5: "Bob"})
    ui, _probe, _roster, _seating = _primed(panel)

    asyncio.run(ui.expand_and_find_desks())

    assert panel.popup_clicks == 0
    assert panel.press_backs == 0
    assert panel.scrolls == []


def test_expanding_seats_purges_departures_without_any_popup():
    panel, _desks = make_panel({1: "Alice", 3: "Bob"})
    ui, _probe, roster, _seating = _primed(panel)

    panel.clear_seat(3)

    asyncio.run(ui.expand_and_find_desks())

    assert panel.popup_clicks == 0
    assert roster.occupant(3) is None


def test_expansion_does_not_sync_in_a_guest_room(_host_room):
    panel, _desks = make_panel({1: "Alice"})
    ui, _probe, roster, _seating = _stack(panel)
    _host_room.is_guest_room = True

    asyncio.run(ui.expand_and_find_desks())

    assert panel.popup_clicks == 0
    assert roster.occupants() == []


def test_sit_at_specific_seat_rejects_an_occupied_target_without_opening_a_popup(_host_room):
    panel, _desks = make_panel({5: "Bob"})
    _ui, _probe, _roster, seating = _primed(panel)

    result = asyncio.run(seating.sit_at_specific_seat(5))

    assert result == {"error": "Seat 5 is already occupied by Bob"}
    assert panel.popup_clicks == 0


def test_sit_at_specific_seat_names_an_unidentified_occupant(_host_room):
    panel, _desks = make_panel({})
    _ui, _probe, _roster, seating = _primed(panel)

    panel.set_occupant(5, "Bob")

    result = asyncio.run(seating.sit_at_specific_seat(5))

    assert result == {"error": f"Seat 5 is already occupied by {UNKNOWN_USERNAME}"}
    assert panel.popup_clicks == 0


def test_sit_at_specific_seat_takes_the_target_seat_and_records_it(_host_room):
    panel, desks = make_panel({1: "Alice"})
    _ui, _probe, roster, seating = _primed(panel)

    result = asyncio.run(seating.sit_at_specific_seat(6))

    assert result == {"success": "Successfully took a seat"}
    assert desks[2].right_seat.clicked == 1
    assert roster.find_seat_of(DEFAULT_ROOM_OWNER) == 6
    assert roster.occupant(6).is_owner is True


def test_sit_at_specific_seat_moves_the_owner_off_the_previous_seat(_host_room):
    panel, _desks = make_panel({1: DEFAULT_ROOM_OWNER}, owner_seats=[1])
    _ui, _probe, roster, seating = _primed(panel)
    assert roster.find_seat_of(DEFAULT_ROOM_OWNER) == 1

    asyncio.run(seating.sit_at_specific_seat(6))

    assert roster.occupant(1) is None
    assert roster.find_seat_of(DEFAULT_ROOM_OWNER) == 6


def test_sit_at_specific_seat_senses_the_target_row_while_scrolling(_host_room):
    panel, desks = make_panel({1: "Alice"})
    _ui, probe, _roster, seating = _primed(panel)
    observed = []
    original = probe.observe_desk

    def spying_observe(desk_index, desk_info):
        observed.append(desk_index)
        return original(desk_index, desk_info)

    probe.observe_desk = spying_observe

    asyncio.run(seating.sit_at_specific_seat(6))

    assert observed == [2]


def test_seat_off_owner_clears_the_owner_from_the_roster(_host_room):
    panel, desks = make_panel({1: DEFAULT_ROOM_OWNER}, owner_seats=[1])
    _ui, _probe, roster, seating = _primed(panel)

    result = asyncio.run(seating.seat_off_owner())

    assert result == {"success": f"Successfully removed {DEFAULT_ROOM_OWNER} from seat 1"}
    assert roster.occupant(1) is None
    # Removing somebody inherently reads their profile once for the confirmation
    # name; the opportunistic sync adds no popup of its own.
    assert panel.popup_clicks == 1


def test_seat_off_specific_seat_clears_that_seat_from_the_roster(_host_room):
    panel, _desks = make_panel({5: "Bob"})
    _ui, _probe, roster, seating = _primed(panel)

    result = asyncio.run(seating.seat_off_specific_seat(5))

    assert result == {"success": "Successfully removed Bob from seat 5"}
    assert roster.occupant(5) is None
    assert panel.popup_clicks == 1


def test_roster_is_untouched_when_removal_fails(_host_room):
    panel, _desks = make_panel({5: "Bob"})
    _ui, _probe, roster, seating = _primed(panel)
    panel.handler.element_finder.wait_for_element_clickable = lambda key, timeout=0: None

    result = asyncio.run(seating.seat_off_specific_seat(5))

    assert "error" in result
    assert roster.find_seat_of("Bob") == 5


def test_user_entry_seat_check_senses_the_row_it_scrolls_to(_host_room):
    """Reservation checks scroll a row into view; sensing it there is free."""
    from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager

    panel, _desks = make_panel({1: "Alice"})
    ui, probe, _roster, _seating = _primed(panel)
    observed = []
    original = probe.observe_desk
    probe.observe_desk = lambda index, info: observed.append(index) or original(index, info)

    checker = SeatCheckManager(panel.handler, ui, probe=probe)
    asyncio.run(checker.check_user_specific_seat("Alice", 9))

    # Seat 9 lives on desk 4.
    assert observed == [4]


def test_a_failed_row_sense_never_aborts_the_reservation_check(_host_room, monkeypatch):
    """Sensing is opportunistic: it must never take the check down with it."""
    from ushareiplay.managers.seat_manager import seat_check as seat_check_module
    from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager

    panel, _desks = make_panel({1: "Alice"})
    ui, probe, _roster, _seating = _primed(panel)

    def exploding_read(handler, desk):
        raise RuntimeError("stale element reference")

    monkeypatch.setattr(seat_check_module, "read_desk", exploding_read)

    checked = []

    async def record(username, seat_desks, seat_number):
        checked.append(seat_number)

    checker = SeatCheckManager(panel.handler, ui, probe=probe)
    checker._handle_occupied_seat = record

    asyncio.run(checker.check_user_specific_seat("Alice", 9))

    assert panel.handler.errors != []
    assert checked == [9]


def test_user_entry_seat_check_reads_no_extra_elements_without_a_probe():
    from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager

    panel, _desks = make_panel({1: "Alice"})
    ui = SeatUIManager(panel.handler)
    original = panel.handler.element_finder.find_child_element
    reads = []

    def recording(desk, key, log_failure=True):
        reads.append(key)
        return original(desk, key, log_failure=log_failure)

    panel.handler.element_finder.find_child_element = recording

    checker = SeatCheckManager(panel.handler, ui)
    asyncio.run(checker.check_user_specific_seat("Alice", 9))

    # Only the target seat's own children; no desk-wide read is spent when there
    # is no roster to feed.
    assert reads == ["left_seat", "left_label"]


def test_seat_manager_exposes_the_shared_roster():
    from ushareiplay.managers.seat_manager import SeatManager

    SeatManager._instance = None
    SeatManager._initialized = False
    handler = SimpleNamespace(
        logger=SimpleNamespace(info=lambda *_a: None, warning=lambda *_a: None),
        config={},
    )
    try:
        manager = SeatManager.get_instance(handler)

        assert manager.get_roster() is manager._ui.roster
        assert manager._ui.probe.roster is manager.get_roster()
    finally:
        SeatManager._instance = None
        SeatManager._initialized = False


def test_expand_desks_scrolls_to_first_row_and_tracks_row_index():
    panel, _desks = make_panel({1: "Alice"})
    ui = SeatUIManager(panel.handler)

    assert ui.current_row_index is None
    asyncio.run(ui.expand_and_find_desks())

    assert ui.current_row_index == 0
    assert panel.swipes != []
    start_x, start_y, end_x, end_y, _duration = panel.swipes[0]
    assert start_x == end_x
    assert end_y > start_y


def test_scroll_to_row_delta_movements():
    panel, desks = make_panel()
    ui = SeatUIManager(panel.handler)
    ui.current_row_index = 0

    panel.swipes.clear()
    ui.scroll_to_row(0, desks)
    assert panel.swipes == []

    ui.scroll_to_row(2, desks)
    assert len(panel.swipes) == 1
    assert ui.current_row_index == 1
    _sx, sy1, _ex, ey1, _ = panel.swipes[0]
    assert ey1 < sy1
    delta_1 = sy1 - ey1

    panel.swipes.clear()
    ui.scroll_to_row(4, desks)
    assert len(panel.swipes) == 1
    assert ui.current_row_index == 2

    panel.swipes.clear()
    ui.scroll_to_row(0, desks)
    assert len(panel.swipes) == 1
    assert ui.current_row_index == 0
    _sx, sy0, _ex, ey0, _ = panel.swipes[0]
    assert ey0 > sy0
    assert (ey0 - sy0) == 2 * delta_1


def test_collapse_seats_resets_current_row_index():
    panel, _desks = make_panel({1: "Alice"})
    ui = SeatUIManager(panel.handler)

    asyncio.run(ui.expand_and_find_desks())
    assert ui.is_expanded is True
    assert ui.current_row_index == 0

    asyncio.run(ui.collapse_seats())
    assert ui.is_expanded is False
    assert ui.current_row_index is None
