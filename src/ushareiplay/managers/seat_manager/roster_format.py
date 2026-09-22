"""Rendering of the Seat Roster into a highlighted, log-readable table.

Kept out of :mod:`ushareiplay.managers.seat_manager.roster`, which owns state and
nothing else. What lives here is presentation: the six-desk layout, the ANSI
highlighting that makes it scannable, and the transition summary that tells a
reader *what changed* rather than only what the room looks like now.

The table is rendered as a list of ``(text, style)`` segments and padded in
terminal cells, because party nicknames are routinely Chinese and a naive
``str.ljust`` would misalign every row they appear on.
"""

import re
import unicodedata
from typing import List, Optional, Tuple

from ushareiplay.managers.seat_manager.desks import (
    OWNER_LABEL,
    SIDES,
    seat_number_of,
)
from ushareiplay.managers.seat_manager.roster import (
    SEAT_NUMBERS,
    UNKNOWN_USERNAME,
    SeatChange,
    SeatRoster,
)

RESET = "\033[0m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"

#: How an empty seat, and an occupied-but-unidentified one, are labelled.
EMPTY_LABEL = "空"
UNIDENTIFIED_LABEL = "未知"

#: Transition kinds, which the summary must keep apart from one another.
MOVE_LABEL = "换位"
ARRIVAL_LABEL = "入座"
DEPARTURE_LABEL = "离座"

#: Longest nickname rendered, in terminal cells. Longer ones are truncated so a
#: single verbose name cannot skew the whole table.
MAX_NAME_CELLS = 16

#: Desk *d* holds seats ``2d+1`` (left) and ``2d+2`` (right).
DESK_COUNT = len(SEAT_NUMBERS) // len(SIDES)

_ANSI = re.compile(r"\033\[[0-9;]*m")

Style = Optional[str]
Cell = List[Tuple[str, Style]]


def display_width(text: str) -> int:
    """Width of ``text`` in terminal cells, ignoring ANSI escape sequences."""
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in _ANSI.sub("", text)
    )


def format_seat_roster(
    roster: SeatRoster,
    changes: Optional[List[SeatChange]] = None,
    *,
    color: bool = True,
) -> str:
    """Render the roster as a framed 12-seat table plus a transition summary.

    ``changes`` are the seat transitions to explain below the table; passing
    none renders the layout alone. ``color`` toggles the ANSI highlighting that
    makes the change stand out in a console.
    """
    transitions = list(changes or [])
    paint = _Painter(color)

    cells = [
        [_seat_cell(roster, seat_number_of(desk_index, side)) for side in SIDES]
        for desk_index in range(DESK_COUNT)
    ]
    cell_width = max(display_width(_plain(cell)) for row in cells for cell in row)

    body = [
        _desk_segments(desk_index, desk_cells, cell_width, paint)
        for desk_index, desk_cells in enumerate(cells)
    ]
    changes_segments = _change_segments(transitions, paint)
    # The summary is widened into the frame rather than allowed to spill past it.
    inner_width = max(
        [_plain_width(body[0])] + [_plain_width(c) for c in changes_segments]
    )

    lines = [_header_line(roster, inner_width, paint)]
    lines += [_row(segments, inner_width, paint) for segments in body]
    if transitions:
        lines.append(_divider_line(len(transitions), inner_width, paint))
        lines += [_row(segments, inner_width, paint) for segments in changes_segments]
    lines.append(paint("└" + "─" * (inner_width + 2) + "┘", CYAN))
    return "\n".join(lines)


class _Painter:
    """Applies ANSI styles, or not, depending on how the caller wants to read it."""

    def __init__(self, enabled: bool):
        self._enabled = enabled

    def __call__(self, text: str, style: Style = None) -> str:
        if not self._enabled or not style:
            return text
        return f"{style}{text}{RESET}"


def _plain(segments) -> str:
    return "".join(text for text, _style in segments)


def _plain_width(segments) -> int:
    return display_width(_plain(segments))


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def _pad_start(text: str, width: int) -> str:
    return " " * max(0, width - display_width(text)) + text


def _fit(text: str, limit: int = MAX_NAME_CELLS) -> str:
    """Truncate ``text`` to ``limit`` cells, marking the cut with an ellipsis."""
    if display_width(text) <= limit:
        return text
    kept = ""
    for char in text:
        if display_width(kept + char) > limit - 1:
            break
        kept += char
    return kept + "…"


def _row(content, inner_width: int, paint: _Painter) -> str:
    """Frame one row, padding its content out to the table's inner width."""
    padding = " " * max(0, inner_width - _plain_width(content))
    return (
        paint("│ ", CYAN)
        + "".join(paint(text, style) for text, style in content)
        + padding
        + paint(" │", CYAN)
    )


def _header_line(roster: SeatRoster, inner_width: int, paint: _Painter) -> str:
    title = f" Seat Roster · {_occupied_count(roster)}/{len(SEAT_NUMBERS)} "
    return paint(f"┌{_centered(title, inner_width + 2)}┐", CYAN)


def _divider_line(count: int, inner_width: int, paint: _Painter) -> str:
    title = f" 变化 Changes ({count}) "
    return paint(f"├{_centered(title, inner_width + 2)}┤", CYAN)


def _centered(title: str, width: int) -> str:
    """Wrap a title in the horizontal rule that fills the given inner width."""
    spanning = max(0, width - display_width(title))
    return "─" * (spanning // 2) + title + "─" * (spanning - spanning // 2)


def _occupied_count(roster: SeatRoster) -> int:
    return sum(
        1
        for seat_number in SEAT_NUMBERS
        if roster.occupant(seat_number) is not None
        or _occupied_in_mask(roster, seat_number)
    )


def _occupied_in_mask(roster: SeatRoster, seat_number: int) -> bool:
    """Fallback occupancy for a seat whose occupant the roster has not recorded."""
    mask = roster.occupancy_mask
    return bool(mask[seat_number - 1]) if len(mask) >= seat_number else False


def _seat_cell(roster: SeatRoster, seat_number: int) -> Cell:
    """One seat: its number, then its occupant, owner badge or empty marker."""
    number = _pad_start(str(seat_number), 2) + " "
    occupant = roster.occupant(seat_number)

    if occupant is None and not _occupied_in_mask(roster, seat_number):
        return [(number, None), (EMPTY_LABEL, DIM)]

    if occupant is None or occupant.username == UNKNOWN_USERNAME:
        cell: Cell = [(number, None), (UNIDENTIFIED_LABEL, YELLOW)]
    else:
        cell = [(number, None), (_fit(occupant.username), GREEN)]

    if occupant is not None and occupant.is_owner:
        cell.append((" ", None))
        cell.append((f"[{OWNER_LABEL}]", YELLOW))
    return cell


def _desk_segments(
    desk_index: int, desk_cells, cell_width: int, paint: _Painter
) -> list:
    """The desk label and both seat cells of one desk row."""
    segments = [(f"Desk {desk_index + 1}", CYAN), (" │ ", CYAN)]
    for position, cell in enumerate(desk_cells):
        if position:
            segments.append((" │ ", CYAN))
        segments.append((_render_cell(cell, cell_width, paint), None))
    return segments


def _render_cell(cell: Cell, width: int, paint: _Painter) -> str:
    """Render one cell and pad it: the padding must not carry the cell's colour."""
    rendered = "".join(paint(text, style) for text, style in cell)
    return rendered + " " * max(0, width - display_width(_plain(cell)))


def _change_segments(changes, paint: _Painter) -> List[list]:
    """One row per transition, with its kind, name and seat movement aligned."""
    del paint  # the kind's own style is enough to tell the transitions apart
    if not changes:
        return []

    names = [_display_name(change) for change in changes]
    name_width = max(display_width(name) for name in names)
    kind_width = max(
        display_width(label) for label, _style in (_transition_of(c) for c in changes)
    )

    rows = []
    for change, name in zip(changes, names):
        label, style = _transition_of(change)
        previous = _pad_start(_seat_text(change.previous_seat), 2)
        current = _pad_start(_seat_text(change.current_seat), 2)
        rows.append(
            [
                (f"{_pad(label, kind_width)} {_pad(name, name_width)}", style),
                (f" {previous} ➔ {current}", DIM),
            ]
        )
    return rows


def _transition_of(change: SeatChange) -> Tuple[str, Style]:
    if change.previous_seat is None:
        return ARRIVAL_LABEL, GREEN
    if change.current_seat is None:
        return DEPARTURE_LABEL, DIM
    return MOVE_LABEL, YELLOW


def _display_name(change: SeatChange) -> str:
    return _fit(change.username or UNIDENTIFIED_LABEL)


def _seat_text(seat_number: Optional[int]) -> str:
    return EMPTY_LABEL if seat_number is None else str(seat_number)
