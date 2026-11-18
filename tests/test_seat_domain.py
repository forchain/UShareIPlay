"""modules/seat/domain.py 纯领域规则与值对象单测。"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from ushareiplay.modules.seat.domain import (
    GUEST_ROOM_ERROR_RESULT,
    Reading,
    SeatError,
    SeatReservation,
    guest_room_guard,
    is_bounds_interactable,
    is_seat_number_label,
    parse_focus_count_text,
)
from ushareiplay.modules.shared.errors import DomainError


def test_seat_error_derives_from_domain_error():
    assert issubclass(SeatError, DomainError)


@pytest.mark.parametrize(
    "label, expected",
    [
        ("1", True),
        ("12", True),
        ("0", False),
        ("13", False),
        ("群主", False),
        ("管理", False),
        ("小明7", False),
        ("", False),
    ],
)
def test_is_seat_number_label_accepts_only_1_to_12(label, expected):
    assert is_seat_number_label(label) is expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("7人专注中", 7),
        ("共12人专注中", 12),
        ("当前 3 人", 3),
        ("", None),
        (None, None),
        ("暂无", None),
    ],
)
def test_parse_focus_count_text(text, expected):
    assert parse_focus_count_text(text) == expected


def test_is_bounds_interactable_rejects_clipped_fragments():
    assert is_bounds_interactable({"x": 28, "y": 566, "width": 309, "height": 207}) is True
    assert is_bounds_interactable({"x": 28, "y": 566, "width": 309, "height": 18}) is False
    assert is_bounds_interactable({"x": 28, "y": 566, "width": 309, "height": 99}) is False
    assert is_bounds_interactable(None) is False


def test_reading_tristate_semantics():
    occ = Reading(True, False, "1", True, False, False, 4)
    emp = Reading(False, True, "", False, True, False, 1)
    unk = Reading(False, False, "", False, False, False, 0)
    assert occ.readable is True
    assert emp.readable is True
    assert unk.readable is False


def test_seat_reservation_value_object():
    now = datetime(2026, 1, 1, 12, 0)
    r = SeatReservation(
        id=1, user_id=2, username="Alice", user_level=3, seat_number=5, start_time=now, duration_hours=3
    )
    assert r.seat_number == 5
    assert r.duration_hours == 3


@pytest.mark.asyncio
async def test_guest_room_guard_short_circuits_when_guest_room():
    class _Svc:
        def __init__(self, guest: bool):
            self.room_state = SimpleNamespace(is_guest_room=guest)

        @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
        async def act(self):
            return {"success": "ok"}

    assert await _Svc(True).act() == GUEST_ROOM_ERROR_RESULT
    assert await _Svc(False).act() == {"success": "ok"}
