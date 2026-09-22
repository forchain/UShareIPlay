"""In-memory Seat Roster: the identity mapping of party seats 1-12 to occupants.

The roster is intentionally free of UI concerns. It only holds state and answers
questions about it; the differential probing that keeps it honest lives in
:mod:`ushareiplay.managers.seat_manager.probe`.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple

#: Placeholder recorded when a seat is occupied but its profile popup never
#: rendered a nickname. Such occupants are tracked as occupancy but never as
#: identities.
UNKNOWN_USERNAME = "Unknown"

SEAT_NUMBERS: Tuple[int, ...] = tuple(range(1, 13))


@dataclass(frozen=True)
class SeatOccupant:
    """A user occupying one party seat."""

    username: str
    seat_number: int
    is_owner: bool = False
    seated_at: datetime = field(default_factory=datetime.now)
    verified: bool = True


@dataclass(frozen=True)
class SeatChange:
    """An identity-level seat transition for one user."""

    username: str
    previous_seat: Optional[int]
    current_seat: Optional[int]


def diff_snapshots(
    before: Mapping[int, str], after: Mapping[int, str]
) -> List[SeatChange]:
    """Compare two seat->username snapshots into per-user seat changes."""
    changes: List[SeatChange] = []
    for username in sorted(set(before.values()) | set(after.values())):
        previous_seat = _seat_of(before, username)
        current_seat = _seat_of(after, username)
        if previous_seat != current_seat:
            changes.append(
                SeatChange(
                    username=username,
                    previous_seat=previous_seat,
                    current_seat=current_seat,
                )
            )
    return changes


def _seat_of(snapshot: Mapping[int, str], username: str) -> Optional[int]:
    for seat_number, occupant in snapshot.items():
        if occupant == username:
            return seat_number
    return None


class SeatRoster:
    """Cached occupancy of seats 1-12 plus the UI signals the cache came from."""

    def __init__(self, clock: Optional[Callable[[], datetime]] = None):
        self._clock = clock or datetime.now
        self._seats: Dict[int, Optional[SeatOccupant]] = {n: None for n in SEAT_NUMBERS}
        self._focus_count: Optional[int] = None
        self._occupancy_mask: Tuple[bool, ...] = (False,) * len(SEAT_NUMBERS)

    @property
    def focus_count(self) -> Optional[int]:
        return self._focus_count

    @property
    def occupancy_mask(self) -> Tuple[bool, ...]:
        return self._occupancy_mask

    def occupant(self, seat_number: int) -> Optional[SeatOccupant]:
        return self._seats.get(seat_number)

    def occupants(self) -> List[SeatOccupant]:
        return [occupant for occupant in self._seats.values() if occupant is not None]

    def is_occupied(self, seat_number: int) -> bool:
        return self._seats.get(seat_number) is not None

    def find_seat_of(self, username: str) -> Optional[int]:
        """Return the cached seat of an identified user, if any."""
        if not username or username == UNKNOWN_USERNAME:
            return None
        for seat_number, occupant in self._seats.items():
            if occupant is None or not occupant.verified:
                continue
            if occupant.username == username:
                return seat_number
        return None

    def snapshot(self) -> Dict[int, str]:
        """Seat -> username for every occupant whose identity is known."""
        return {
            seat_number: occupant.username
            for seat_number, occupant in self._seats.items()
            if occupant is not None and occupant.verified and occupant.username != UNKNOWN_USERNAME
        }

    def set_occupant(
        self,
        seat_number: int,
        username: str,
        *,
        is_owner: bool = False,
        verified: bool = True,
        now: Optional[datetime] = None,
    ) -> SeatOccupant:
        """Record the occupant of a seat, keeping ``seated_at`` across reconfirmations."""
        previous = self._seats.get(seat_number)
        if previous is not None and previous.username == username:
            seated_at = previous.seated_at
        else:
            seated_at = now or self._clock()

        occupant = SeatOccupant(
            username=username,
            seat_number=seat_number,
            is_owner=is_owner,
            seated_at=seated_at,
            verified=verified,
        )
        self._seats[seat_number] = occupant
        return occupant

    def clear_seat(self, seat_number: int) -> Optional[SeatOccupant]:
        """Drop a seat's occupant, returning whoever was there."""
        previous = self._seats.get(seat_number)
        self._seats[seat_number] = None
        return previous

    def invalidate(self, seat_number: int) -> None:
        """Mark a seat's identity as suspect, forcing the next probe to re-read it.

        Used when a popup read contradicts the cache: the occupancy signal said
        nothing changed, so only an explicit invalidation gets the seat re-probed.
        """
        occupant = self._seats.get(seat_number)
        if occupant is None or not occupant.verified:
            return
        self._seats[seat_number] = replace(occupant, verified=False)

    def note_focus_count(self, focus_count: Optional[int]) -> None:
        self._focus_count = focus_count

    def note_occupancy(self, seat_number: int, occupied: bool) -> None:
        """Update one entry of the cached occupancy mask."""
        if seat_number not in self._seats:
            return
        mask = list(self._occupancy_mask)
        mask[seat_number - 1] = bool(occupied)
        self._occupancy_mask = tuple(mask)

    def note_occupancy_mask(self, occupancy_mask: Iterable[bool]) -> None:
        mask = tuple(bool(value) for value in occupancy_mask)
        if len(mask) != len(SEAT_NUMBERS):
            return
        self._occupancy_mask = mask

    def is_stale(self, *, focus_count: Optional[int], occupancy_mask: Iterable[bool]) -> bool:
        """Whether the cached roster disagrees with the live seat panel.

        Drives the differential probe: a clean roster costs no profile popups.
        """
        if focus_count != self._focus_count:
            return True
        if tuple(bool(value) for value in occupancy_mask) != self._occupancy_mask:
            return True
        return any(
            occupant is not None and not occupant.verified
            for occupant in self._seats.values()
        )

    def reset(self) -> None:
        """Forget everything: seat identities belong to one party room."""
        self._seats = {n: None for n in SEAT_NUMBERS}
        self._focus_count = None
        self._occupancy_mask = (False,) * len(SEAT_NUMBERS)
