import asyncio

from tests.seat_panel import make_panel

from ushareiplay.managers.seat_manager.desks import read_desk
from ushareiplay.managers.seat_manager.probe import SeatProbe
from ushareiplay.managers.seat_manager.roster import (
    UNKNOWN_USERNAME,
    SeatChange,
    SeatRoster,
)


class FakeSeatUI:
    """Records the rows the probe scrolls to; scrolling is the probe's only UI cost."""

    def __init__(self, panel):
        self.panel = panel

    def scroll_to_row(self, desk_index, seat_desks, duration=100):
        self.panel.scrolls.append(desk_index)


def _mask(occupied_seats):
    return tuple(seat in occupied_seats for seat in range(1, 13))


def _probe(panel, focus_count=None):
    roster = SeatRoster()
    ui = FakeSeatUI(panel)
    probe = SeatProbe(
        panel.handler, ui, roster, focus_count_provider=lambda: focus_count
    )
    return probe, roster, ui


def _synced(panel, focus_count=None):
    """Run one sync so the roster begins consistent with the panel."""
    probe, roster, ui = _probe(panel, focus_count)
    asyncio.run(probe.sync(panel.desks, focus_count=focus_count))
    panel.popup_clicks = 0
    panel.press_backs = 0
    panel.scrolls.clear()
    return probe, roster, ui


def test_first_sync_probes_every_occupied_seat():
    panel, desks = make_panel({1: "Alice", 5: "Bob", 12: "Carol"})
    probe, roster, _ui = _probe(panel)

    result = asyncio.run(probe.sync(desks, focus_count=3))

    assert panel.popup_clicks == 3
    assert result.probed_seats == [1, 5, 12]
    assert roster.find_seat_of("Alice") == 1
    assert roster.find_seat_of("Bob") == 5
    assert roster.find_seat_of("Carol") == 12


def test_first_sync_closes_every_profile_popup_it_opens():
    panel, desks = make_panel({2: "Alice", 4: "Bob"})
    probe, _roster, _ui = _probe(panel)

    asyncio.run(probe.sync(desks, focus_count=2))

    assert panel.press_backs == 2
    assert panel.opened_popup is None


def test_sync_is_a_no_op_when_nothing_changed():
    panel, desks = make_panel({1: "Alice", 3: "Bob"})
    probe, roster, _ui = _synced(panel, focus_count=2)

    result = asyncio.run(probe.sync(desks, focus_count=2))

    assert panel.popup_clicks == 0
    assert panel.scrolls == []
    assert result.probed_seats == []
    assert result.cleared_seats == []
    assert result.changes == []
    assert roster.find_seat_of("Alice") == 1


def test_sync_purges_departures_without_opening_profile_popups():
    panel, desks = make_panel({1: "Alice", 3: "Bob", 5: "Carol"})
    probe, roster, _ui = _synced(panel, focus_count=3)

    panel.clear_seat(3)

    result = asyncio.run(probe.sync(desks, focus_count=2))

    assert panel.popup_clicks == 0
    assert result.cleared_seats == [3]
    assert roster.occupant(3) is None
    assert roster.find_seat_of("Bob") is None
    assert roster.find_seat_of("Alice") == 1
    assert roster.find_seat_of("Carol") == 5


def test_sync_probes_only_the_newly_occupied_seat():
    panel, desks = make_panel({1: "Alice", 3: "Bob"})
    probe, roster, _ui = _synced(panel, focus_count=2)

    panel.set_occupant(7, "Carol")

    result = asyncio.run(probe.sync(desks, focus_count=3))

    assert panel.popup_clicks == 1
    assert panel.scrolls == [3]
    assert result.probed_seats == [7]
    assert roster.find_seat_of("Carol") == 7
    assert roster.find_seat_of("Alice") == 1


def test_sync_retains_cached_usernames_for_unchanged_occupants():
    panel, desks = make_panel({1: "Alice", 5: "Bob"})
    probe, roster, _ui = _synced(panel, focus_count=2)
    originally_seated_at = {1: roster.occupant(1).seated_at, 5: roster.occupant(5).seated_at}

    panel.set_occupant(9, "Carol")

    asyncio.run(probe.sync(desks, focus_count=3))

    assert roster.find_seat_of("Alice") == 1
    assert roster.find_seat_of("Bob") == 5
    assert roster.occupant(1).seated_at == originally_seated_at[1]
    assert roster.occupant(5).seated_at == originally_seated_at[5]


def test_sync_scrubs_desk_rows_that_became_empty_entirely():
    panel, desks = make_panel({1: "Alice", 7: "Bob", 8: "Carol"})
    probe, roster, _ui = _synced(panel, focus_count=3)

    panel.clear_seat(7)
    panel.clear_seat(8)

    result = asyncio.run(probe.sync(desks, focus_count=1))

    assert sorted(result.cleared_seats) == [7, 8]
    assert panel.popup_clicks == 0
    assert [occupant.username for occupant in roster.occupants()] == ["Alice"]


def test_sync_scrolls_a_probed_row_only_once():
    panel, desks = make_panel({1: "Alice"})
    probe, roster, _ui = _synced(panel, focus_count=1)

    panel.set_occupant(7, "Bob")
    panel.set_occupant(8, "Carol")

    asyncio.run(probe.sync(desks, focus_count=3))

    assert panel.popup_clicks == 2
    assert panel.scrolls == [3]
    assert roster.find_seat_of("Bob") == 7
    assert roster.find_seat_of("Carol") == 8


def test_sync_records_unknown_when_the_profile_popup_never_renders_a_name():
    panel, desks = make_panel({1: "Alice"}, popup_failures=[1])
    probe, roster, _ui = _probe(panel)

    result = asyncio.run(probe.sync(desks, focus_count=1))

    assert panel.popup_clicks == 1
    assert result.probed_seats == [1]
    assert roster.occupant(1).username == UNKNOWN_USERNAME
    assert roster.is_occupied(1) is True
    assert roster.find_seat_of(UNKNOWN_USERNAME) is None
    assert panel.press_backs == 1


def test_sync_presses_no_back_when_the_popup_click_never_landed():
    panel, desks = make_panel({1: "Alice"})
    probe, roster, _ui = _probe(panel)

    def exploding_click():
        raise RuntimeError("stale element reference")

    # A click that raises opens no profile, so a Back press here would land on
    # the room itself — which the app may read as "leave the party".
    panel.desks[0].left_state.click = exploding_click

    result = asyncio.run(probe.sync(desks, focus_count=1))

    assert panel.handler.errors != []
    assert panel.popup_clicks == 0
    assert panel.press_backs == 0
    assert result.probed_seats == [1]
    assert roster.occupant(1).username == UNKNOWN_USERNAME


def test_sync_keeps_probing_after_one_popup_fails():
    panel, desks = make_panel({1: "Alice", 3: "Bob"}, popup_failures=[1])
    probe, roster, _ui = _probe(panel)

    result = asyncio.run(probe.sync(desks, focus_count=2))

    assert panel.popup_clicks == 2
    assert result.probed_seats == [1, 3]
    assert roster.occupant(1).username == UNKNOWN_USERNAME
    assert roster.find_seat_of("Bob") == 3


def test_sync_keeps_probing_after_a_popup_render_failure():
    panel, desks = make_panel({1: "Alice", 3: "Bob"})
    probe, roster, _ui = _probe(panel)
    original = panel.handler.element_finder.wait_for_any_element
    calls = {"count": 0}

    def failing_once(keys):
        if calls["count"] == 0:
            calls["count"] += 1
            raise RuntimeError("popup render timeout")
        return original(keys)

    panel.handler.element_finder.wait_for_any_element = failing_once

    result = asyncio.run(probe.sync(desks))

    assert panel.handler.errors != []
    assert result.probed_seats == [1, 3]
    assert roster.occupant(1).username == UNKNOWN_USERNAME
    assert roster.find_seat_of("Bob") == 3


def test_sync_keeps_cached_occupancy_when_reading_a_desk_raises():
    panel, desks = make_panel({1: "Alice", 3: "Bob"})
    probe, roster, _ui = _probe(panel)
    original = panel.handler.element_finder.find_child_element

    def failing_desk_zero(desk, key, log_failure=True):
        if desk.index == 0:
            raise RuntimeError("stale element reference")
        return original(desk, key, log_failure=log_failure)

    panel.handler.element_finder.find_child_element = failing_desk_zero

    result = asyncio.run(probe.sync(desks))

    assert panel.handler.errors != []
    assert result.probed_seats == [3]
    assert roster.find_seat_of("Bob") == 3


def test_sync_probes_seats_that_are_occupied_but_unverified():
    panel, desks = make_panel({1: "Alice"})
    probe, roster, _ui = _synced(panel, focus_count=1)
    roster.set_occupant(1, UNKNOWN_USERNAME, verified=False)

    result = asyncio.run(probe.sync(desks, focus_count=1))

    assert panel.popup_clicks == 1
    assert result.probed_seats == [1]
    assert roster.find_seat_of("Alice") == 1


def test_sync_updates_cached_focus_count_and_occupancy_mask():
    panel, desks = make_panel({2: "Alice", 4: "Bob"})
    probe, roster, _ui = _probe(panel)

    asyncio.run(probe.sync(desks, focus_count=7))

    assert roster.focus_count == 7
    assert roster.occupancy_mask == _mask({2, 4})


def test_sync_falls_back_to_the_injected_focus_count_provider():
    panel, desks = make_panel({1: "Alice"})
    probe, roster, _ui = _probe(panel, focus_count=4)

    asyncio.run(probe.sync(desks))

    assert roster.focus_count == 4


def test_sync_reports_a_user_moving_between_seats():
    panel, desks = make_panel({3: "Alice"})
    probe, roster, _ui = _synced(panel, focus_count=1)

    panel.clear_seat(3)
    panel.set_occupant(9, "Alice")

    result = asyncio.run(probe.sync(desks, focus_count=1))

    assert result.changes == [
        SeatChange(username="Alice", previous_seat=3, current_seat=9)
    ]
    assert roster.find_seat_of("Alice") == 9


def test_sync_reports_a_move_onto_a_seat_whose_previous_occupant_changed():
    panel, desks = make_panel({3: "Alice"})
    probe, roster, _ui = _synced(panel, focus_count=1)

    # Alice moves to 5 while Bob takes the seat she left. Neither seat went
    # empty, so only a popup read can tell the two of them apart.
    panel.clear_seat(3)
    panel.set_occupant(3, "Bob")
    panel.set_occupant(5, "Alice")

    result = asyncio.run(probe.sync(desks, focus_count=2))

    assert result.changes == [
        SeatChange(username="Alice", previous_seat=3, current_seat=5)
    ]
    assert roster.find_seat_of("Alice") == 5
    # Bob's seat is left unrecorded rather than mislabelled, so the next probe
    # reads it again instead of reporting Alice twice.
    assert roster.occupant(3) is None


def test_sync_reports_a_departure_as_an_unseating_change():
    panel, desks = make_panel({3: "Alice"})
    probe, _roster, _ui = _synced(panel, focus_count=1)

    panel.clear_seat(3)

    result = asyncio.run(probe.sync(desks, focus_count=0))

    assert result.changes == [
        SeatChange(username="Alice", previous_seat=3, current_seat=None)
    ]


def test_sync_returns_an_empty_result_without_seat_desks():
    panel, _desks = make_panel({1: "Alice"})
    probe, roster, _ui = _probe(panel)

    result = asyncio.run(probe.sync(None))

    assert result.probed_seats == []
    assert result.changes == []
    assert roster.occupants() == []


def test_sync_stops_before_probing_when_the_guard_seat_is_occupied():
    panel, desks = make_panel({3: "Alice", 5: "Bob"})
    probe, roster, _ui = _probe(panel)

    result = asyncio.run(probe.sync(desks, focus_count=2, guard_seat=3))

    assert result.blocked_seat == 3
    assert result.probed_seats == []
    assert panel.popup_clicks == 0
    assert panel.scrolls == []
    assert roster.is_occupied(3) is True
    assert roster.occupant(3).username == UNKNOWN_USERNAME
    assert roster.occupant(3).verified is False


def test_sync_still_probes_when_the_guard_seat_is_empty():
    panel, desks = make_panel({3: "Alice"})
    probe, roster, _ui = _probe(panel)

    result = asyncio.run(probe.sync(desks, focus_count=1, guard_seat=5))

    assert result.blocked_seat is None
    assert result.probed_seats == [3]
    assert panel.popup_clicks == 1


def test_sync_purges_departures_even_when_the_guard_seat_is_occupied():
    panel, desks = make_panel({3: "Alice", 5: "Bob"})
    probe, roster, _ui = _synced(panel, focus_count=2)

    panel.clear_seat(5)

    asyncio.run(probe.sync(desks, focus_count=2, guard_seat=3))

    assert panel.popup_clicks == 0
    assert roster.occupant(5) is None


def test_sync_marks_the_owner_flag_from_the_desk_label():
    panel, desks = make_panel({1: "Alice"}, owner_seats=[1])
    probe, roster, _ui = _probe(panel)

    asyncio.run(probe.sync(desks, focus_count=1))

    assert roster.occupant(1).is_owner is True


def test_observe_desk_clears_a_seat_that_became_empty():
    panel, desks = make_panel({1: "Alice"})
    probe, roster, _ui = _synced(panel, focus_count=1)

    panel.clear_seat(1)
    desk_info = _read_desk(panel, desks[0])

    changed = probe.observe_desk(0, desk_info)

    assert changed == [1]
    assert roster.occupant(1) is None
    assert list(roster.occupancy_mask)[0] is False
    assert panel.popup_clicks == 0


def test_observe_desk_marks_a_newly_occupied_seat_as_unverified():
    panel, desks = make_panel({1: "Alice"})
    probe, roster, _ui = _synced(panel, focus_count=1)

    panel.set_occupant(2, "Bob")
    desk_info = _read_desk(panel, desks[0])

    changed = probe.observe_desk(0, desk_info)

    assert changed == [2]
    assert roster.occupant(2).verified is False
    assert roster.find_seat_of("Bob") is None
    assert roster.is_occupied(2) is True
    assert panel.popup_clicks == 0


def test_observe_desk_leaves_an_identified_occupant_untouched():
    panel, desks = make_panel({1: "Alice"})
    probe, roster, _ui = _synced(panel, focus_count=1)
    seated_at = roster.occupant(1).seated_at

    desk_info = _read_desk(panel, desks[0])

    changed = probe.observe_desk(0, desk_info)

    assert changed == []
    assert roster.occupant(1).verified is True
    assert roster.occupant(1).username == "Alice"
    assert roster.occupant(1).seated_at == seated_at


def test_observe_desk_updates_both_sides_of_the_desk():
    panel, desks = make_panel({1: "Alice", 2: "Bob"})
    probe, roster, _ui = _synced(panel, focus_count=2)

    panel.clear_seat(1)
    panel.clear_seat(2)
    desk_info = _read_desk(panel, desks[0])

    changed = probe.observe_desk(0, desk_info)

    assert sorted(changed) == [1, 2]
    assert list(roster.occupancy_mask)[:2] == [False, False]


def _read_desk(panel, desk):
    return read_desk(panel.handler, desk)
