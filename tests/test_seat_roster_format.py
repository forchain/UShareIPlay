"""Ticket #309: Seat Roster status rendering and seat-change summaries."""

from tests.seat_panel import change_rows

from ushareiplay.managers.seat_manager.roster import (
    UNKNOWN_USERNAME,
    SeatChange,
    SeatRoster,
)
from ushareiplay.managers.seat_manager.roster_format import (
    display_width,
    format_seat_roster,
    strip_ansi,
)


def _roster(occupants=None, *, owner_seats=(), unidentified_seats=()):
    roster = SeatRoster()
    for seat_number, username in (occupants or {}).items():
        roster.set_occupant(seat_number, username, is_owner=seat_number in owner_seats)
        roster.note_occupancy(seat_number, True)
    for seat_number in unidentified_seats:
        roster.set_occupant(seat_number, UNKNOWN_USERNAME, verified=False)
        roster.note_occupancy(seat_number, True)
    return roster


def _desk_cells(text, desk_number):
    """The left/right seat cells of one desk row, stripped of frame characters."""
    row = next(
        line for line in text.splitlines() if line.startswith(f"│ Desk {desk_number} │")
    )
    return [cell.strip() for cell in row.split("│")][2:4]


def _line_widths(text):
    return {display_width(line) for line in text.splitlines()}


def test_empty_room_renders_every_seat_of_every_desk_as_empty():
    text = format_seat_roster(SeatRoster(), color=False)

    assert text == "\n".join(
        [
            "┌── Seat Roster · 0/12 ──┐",
            "│ Desk 1 │  1 空 │  2 空 │",
            "│ Desk 2 │  3 空 │  4 空 │",
            "│ Desk 3 │  5 空 │  6 空 │",
            "│ Desk 4 │  7 空 │  8 空 │",
            "│ Desk 5 │  9 空 │ 10 空 │",
            "│ Desk 6 │ 11 空 │ 12 空 │",
            "└────────────────────────┘",
        ]
    )


def test_status_shows_occupants_and_counts_them_in_the_header():
    roster = _roster({1: "Alice", 4: "Bob", 7: "Carol"})

    text = format_seat_roster(roster, color=False)

    assert "Seat Roster · 3/12" in text
    assert "Alice" in _desk_cells(text, 1)[0]
    assert "Bob" in _desk_cells(text, 2)[1]
    assert "Carol" in _desk_cells(text, 4)[0]


def test_status_marks_the_room_owner_seat_with_a_badge():
    roster = _roster({1: "Alice", 4: "Bob"}, owner_seats={4})

    text = format_seat_roster(roster, color=False)

    assert _desk_cells(text, 1)[0].endswith("Alice")
    assert _desk_cells(text, 2)[1] == "4 Bob [群主]"


def test_each_desk_row_pairs_its_two_consecutive_seat_numbers_left_to_right():
    roster = _roster({2: "Alice", 5: "Bob", 10: "Carol"})

    text = format_seat_roster(roster, color=False)

    for desk_index in range(6):
        left_cell, right_cell = _desk_cells(text, desk_index + 1)
        assert left_cell.startswith(f"{desk_index * 2 + 1} ")
        assert right_cell.startswith(f"{desk_index * 2 + 2} ")


def test_status_shows_an_unidentified_occupant_as_occupied_without_a_name():
    roster = _roster(unidentified_seats=(6,))

    text = format_seat_roster(roster, color=False)

    assert "Seat Roster · 1/12" in text
    assert _desk_cells(text, 3)[1] == "6 未知"


def test_status_keeps_every_row_aligned_with_wide_usernames():
    roster = _roster({1: "李雷", 4: "韩梅梅", 7: "Alice"})

    text = format_seat_roster(roster, color=False)

    assert len(_line_widths(text)) == 1


def test_status_truncates_an_overlong_username_to_keep_rows_aligned():
    roster = _roster({1: "A" * 40})

    text = format_seat_roster(roster, color=False)

    assert "A" * 40 not in text
    assert "…" in text
    assert len(_line_widths(text)) == 1


def test_status_without_changes_has_no_changes_block():
    text = format_seat_roster(_roster({2: "Alice"}), color=False)

    assert "变化" not in text
    assert "➔" not in text
    assert text.splitlines()[-1].startswith("└")


def test_changes_block_names_moves_arrivals_and_departures_distinctly():
    roster = _roster({3: "Alice", 5: "Bob"})
    changes = [
        SeatChange(username="Bob", previous_seat=5, current_seat=9),
        SeatChange(username="Dave", previous_seat=None, current_seat=7),
        SeatChange(username="Carol", previous_seat=4, current_seat=None),
    ]

    text = format_seat_roster(roster, changes=changes, color=False)

    assert ["换位", "Bob", "5", "➔", "9"] in change_rows(text)
    assert ["入座", "Dave", "空", "➔", "7"] in change_rows(text)
    assert ["离座", "Carol", "4", "➔", "空"] in change_rows(text)


def test_changes_block_names_an_unidentified_departure():
    changes = [
        SeatChange(username=UNKNOWN_USERNAME, previous_seat=5, current_seat=None)
    ]

    text = format_seat_roster(SeatRoster(), changes=changes, color=False)

    assert ["离座", "未知", "5", "➔", "空"] in change_rows(text)


def test_strip_ansi_removes_the_highlighting():
    assert strip_ansi("\033[32mAlice\033[0m") == "Alice"


def test_changes_block_lists_several_concurrent_arrivals_and_departures():
    changes = [
        SeatChange(username="Alice", previous_seat=None, current_seat=1),
        SeatChange(username="Bob", previous_seat=None, current_seat=2),
        SeatChange(username="Carol", previous_seat=3, current_seat=None),
        SeatChange(username="Dave", previous_seat=4, current_seat=None),
    ]

    text = format_seat_roster(SeatRoster(), changes=changes, color=False)

    rows = change_rows(text)
    assert [row[0] for row in rows] == ["入座", "入座", "离座", "离座"]
    assert [row[1] for row in rows] == ["Alice", "Bob", "Carol", "Dave"]


def test_changes_block_is_framed_and_counts_the_transitions():
    changes = [SeatChange(username="Bob", previous_seat=5, current_seat=9)]

    text = format_seat_roster(SeatRoster(), changes=changes, color=False)

    assert "变化 Changes (1)" in text
    assert len(_line_widths(text)) == 1
    assert text.splitlines()[-1].startswith("└")


def test_status_highlights_occupants_badges_empties_and_the_frame():
    roster = _roster({1: "Alice"}, owner_seats={1})

    text = format_seat_roster(roster, color=True)

    assert "\033[32mAlice\033[0m" in text
    assert "\033[33m[群主]\033[0m" in text
    assert "\033[2m空\033[0m" in text
    assert "\033[36m│" in text


def test_status_emits_no_escape_sequences_when_color_is_disabled():
    roster = _roster({1: "Alice"}, owner_seats={1})
    changes = [SeatChange(username="Bob", previous_seat=5, current_seat=9)]

    text = format_seat_roster(roster, changes=changes, color=False)

    assert "\033" not in text


def test_roster_format_status_renders_its_own_cached_state():
    roster = _roster({2: "Alice"})
    changes = [SeatChange(username="Bob", previous_seat=4, current_seat=None)]

    assert roster.format_status(changes=changes, color=False) == format_seat_roster(
        roster, changes=changes, color=False
    )


def test_roster_format_status_defaults_to_highlighted_output():
    text = _roster({2: "Alice"}).format_status()

    assert "\033[32mAlice\033[0m" in text
