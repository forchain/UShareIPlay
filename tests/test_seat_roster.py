from datetime import datetime, timedelta

from ushareiplay.managers.seat_manager.roster import (
    UNKNOWN_USERNAME,
    SeatChange,
    SeatOccupant,
    SeatRoster,
    diff_snapshots,
)


def _roster() -> SeatRoster:
    return SeatRoster()


def test_new_roster_reports_all_twelve_seats_empty():
    roster = _roster()

    assert list(roster.occupancy_mask) == [False] * 12
    assert roster.occupants() == []
    for seat_number in range(1, 13):
        assert roster.occupant(seat_number) is None
        assert roster.is_occupied(seat_number) is False


def test_set_occupant_records_username_owner_flag_and_timestamp():
    roster = _roster()

    occupant = roster.set_occupant(5, "Alice", is_owner=True)

    assert occupant.username == "Alice"
    assert occupant.seat_number == 5
    assert occupant.is_owner is True
    assert occupant.verified is True
    assert isinstance(occupant.seated_at, datetime)
    assert roster.occupant(5) == occupant
    assert roster.is_occupied(5) is True


def test_set_occupant_preserves_seated_at_when_the_same_user_is_reconfirmed():
    roster = _roster()
    first = roster.set_occupant(3, "Alice")

    second = roster.set_occupant(3, "Alice")

    assert second.seated_at == first.seated_at
    assert second.seat_number == 3


def test_set_occupant_starts_a_new_timestamp_when_a_different_user_takes_the_seat():
    roster = _roster()
    first = roster.set_occupant(3, "Alice", now=datetime(2026, 1, 1, 10, 0, 0))

    second = roster.set_occupant(3, "Bob", now=datetime(2026, 1, 1, 11, 0, 0))

    assert second.seated_at == datetime(2026, 1, 1, 11, 0, 0)
    assert second.seated_at != first.seated_at


def test_find_seat_of_returns_cached_seat_for_known_username():
    roster = _roster()
    roster.set_occupant(7, "Alice")

    assert roster.find_seat_of("Alice") == 7
    assert roster.find_seat_of("Bob") is None


def test_find_seat_of_can_include_a_doubted_occupant():
    """Our own seat may be doubted and still be where we are sitting."""
    roster = _roster()
    roster.set_occupant(7, "Alice")
    roster.invalidate(7)

    assert roster.find_seat_of("Alice") is None
    assert roster.find_seat_of("Alice", include_doubted=True) == 7


def test_set_occupant_releases_the_same_user_from_the_seat_they_left():
    roster = _roster()
    roster.set_occupant(3, "Alice")
    roster.note_occupancy(3, True)

    roster.set_occupant(5, "Alice")

    assert roster.find_seat_of("Alice") == 5
    assert roster.occupant(3) is None
    assert roster.snapshot() == {5: "Alice"}
    # Seat 3 is still somebody's seat in the room, just not an identified one:
    # the occupancy mask belongs to the panel, not to the identity map.
    assert roster.occupancy_mask[2] is True


def test_set_occupant_leaves_unidentified_placeholders_on_several_seats():
    roster = _roster()
    roster.set_occupant(1, UNKNOWN_USERNAME, verified=False)
    roster.set_occupant(2, UNKNOWN_USERNAME, verified=False)

    assert roster.is_occupied(1) is True
    assert roster.is_occupied(2) is True


def test_find_seat_of_skips_unverified_occupants_that_were_never_identified():
    roster = _roster()
    roster.set_occupant(7, "Unknown", verified=False)

    assert roster.is_occupied(7) is True
    assert roster.find_seat_of("Unknown") is None


def test_clear_seat_returns_previous_occupant_and_frees_the_seat():
    roster = _roster()
    roster.set_occupant(4, "Alice")

    removed = roster.clear_seat(4)

    assert removed.username == "Alice"
    assert roster.occupant(4) is None
    assert roster.clear_seat(4) is None


def test_note_focus_count_and_note_occupancy_refresh_the_cached_snapshot():
    roster = _roster()

    roster.note_focus_count(6)
    roster.note_occupancy(1, True)

    assert roster.focus_count == 6
    assert list(roster.occupancy_mask)[0] is True
    assert list(roster.occupancy_mask)[1] is False


def test_is_stale_when_the_focus_count_changed():
    roster = _roster()
    roster.note_focus_count(5)
    roster.note_occupancy_mask([False] * 12)

    assert roster.is_stale(focus_count=6, occupancy_mask=[False] * 12) is True
    assert roster.is_stale(focus_count=5, occupancy_mask=[False] * 12) is False


def test_is_stale_when_the_occupancy_mask_changed():
    roster = _roster()
    roster.note_focus_count(5)
    roster.note_occupancy_mask([False] * 12)

    mask_with_seat_one = [True] + [False] * 11

    assert roster.is_stale(focus_count=5, occupancy_mask=mask_with_seat_one) is True


def test_is_stale_while_an_occupied_seat_is_still_unverified():
    roster = _roster()
    mask = [False, False, True] + [False] * 9
    roster.note_focus_count(5)
    roster.note_occupancy_mask(mask)
    roster.set_occupant(3, "Unknown", verified=False)
    roster.note_occupancy_mask(mask)

    assert roster.is_stale(focus_count=5, occupancy_mask=mask) is True

    roster.set_occupant(3, "Alice", verified=True)

    assert roster.is_stale(focus_count=5, occupancy_mask=mask) is False


def test_reset_drops_every_cached_seat_count_and_mask():
    roster = _roster()
    roster.set_occupant(3, "Alice")
    roster.note_focus_count(5)
    roster.note_occupancy_mask([True] + [False] * 11)

    roster.reset()

    assert roster.occupants() == []
    assert roster.focus_count is None
    assert list(roster.occupancy_mask) == [False] * 12


def test_snapshot_only_reports_identified_occupants():
    roster = _roster()
    roster.set_occupant(1, "Alice")
    roster.set_occupant(2, "Unknown", verified=False)
    roster.set_occupant(3, "Bob", verified=True)

    assert roster.snapshot() == {1: "Alice", 3: "Bob"}


def test_snapshot_keeps_the_last_known_name_of_a_doubted_occupant():
    """A doubted name is still a name: dropping it would read a seat that was
    merely re-read as a fresh arrival rather than as the move it actually was."""
    roster = _roster()
    roster.set_occupant(3, "Alice")

    roster.invalidate(3)

    assert roster.occupant(3).verified is False
    assert roster.snapshot() == {3: "Alice"}


def test_diff_snapshots_reports_seated_unseated_and_shifted_users():
    before = {1: "Alice", 5: "Bob", 9: "Carol"}
    after = {1: "Alice", 5: "Carol", 7: "Dave"}

    assert diff_snapshots(before, after) == [
        SeatChange(username="Bob", previous_seat=5, current_seat=None),
        SeatChange(username="Carol", previous_seat=9, current_seat=5),
        SeatChange(username="Dave", previous_seat=None, current_seat=7),
    ]


def test_diff_snapshots_is_empty_when_nothing_moved():
    snapshot = {1: "Alice", 2: "Bob"}

    assert diff_snapshots(snapshot, dict(snapshot)) == []


def test_invalidate_forces_an_identified_seat_to_be_probed_again():
    roster = _roster()
    mask = [False, False, True] + [False] * 9
    roster.set_occupant(3, "Alice")
    roster.note_occupancy_mask(mask)
    roster.note_focus_count(1)

    assert roster.is_stale(focus_count=1, occupancy_mask=mask) is False

    roster.invalidate(3)

    assert roster.occupant(3).username == "Alice"
    assert roster.occupant(3).verified is False
    assert roster.is_stale(focus_count=1, occupancy_mask=mask) is True


def test_invalidate_ignores_an_empty_seat():
    roster = _roster()

    roster.invalidate(4)

    assert roster.occupant(4) is None


def test_seat_occupant_defaults_to_verified_with_a_timestamp():
    occupant = SeatOccupant(username="Alice", seat_number=1)

    assert occupant.verified is True
    assert occupant.is_owner is False
    assert occupant.seated_at is not None


def test_seated_at_uses_the_injected_clock():
    now = datetime(2026, 2, 3, 4, 5, 6)
    roster = SeatRoster(clock=lambda: now)

    occupant = roster.set_occupant(2, "Alice")

    assert occupant.seated_at == now
    assert occupant.seated_at + timedelta(seconds=1) > now
