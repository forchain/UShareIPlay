"""Seat panel geometry and desk reading.

The seat panel is six desk containers, each holding a left and a right seat.
Seat numbers follow the panel layout: desk *d* holds seats ``2d+1`` (left) and
``2d+2`` (right), so seats 1-12 map onto desks 1-6 in reading order.

Occupancy is derivable from element presence alone: a seat's state child exists
only when somebody is sitting there, which is what makes a zero-click occupancy
read possible.
"""

from typing import Optional

#: Label text shown on the badge of the room owner's seat.
OWNER_LABEL = "群主"

SIDES = ("left", "right")


def seat_number_of(desk_index: int, side: str) -> int:
    """Seat number sitting at the given side of the given desk."""
    return desk_index * 2 + (1 if side == "left" else 2)


def desk_index_of(seat_number: int) -> int:
    return (seat_number - 1) // 2


def side_of(seat_number: int) -> str:
    return "left" if seat_number % 2 else "right"


def adjacent_seat_number(seat_number: int) -> int:
    """The other seat sharing this seat's desk."""
    return seat_number + 1 if seat_number % 2 else seat_number - 1


def read_desk(handler, desk) -> dict:
    """Read one desk container into left/right seat descriptors.

    Every field is derived from element presence or label text, so a read never
    opens a profile popup.
    """
    left_state = _child(handler, desk, "left_state")
    right_state = _child(handler, desk, "right_state")
    left_label = _child(handler, desk, "left_label")
    right_label = _child(handler, desk, "right_label")

    return {
        "left": _seat_descriptor(
            handler, desk, "left", left_state, left_label
        ),
        "right": _seat_descriptor(
            handler, desk, "right", right_state, right_label
        ),
    }


def _seat_descriptor(handler, desk, side, state_element, label_element) -> dict:
    label = label_element.text if label_element is not None else ""
    return {
        "element": _child(handler, desk, f"{side}_seat"),
        "state": state_element,
        "label": label,
        "occupied": state_element is not None,
        "is_owner": label == OWNER_LABEL,
        "side": side,
    }


def _child(handler, desk, key) -> Optional[object]:
    return handler.element_finder.find_child_element(desk, key, log_failure=False)
