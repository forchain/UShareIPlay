"""Seat change domain events.

The Seat Roster reports *state*; these events report *transitions*, which is what
automations (auto-accompany, greetings) actually react to.
"""

from dataclasses import dataclass
from typing import Union

from ushareiplay.managers.seat_manager.roster import SeatChange


@dataclass(frozen=True)
class UserSeatedEvent:
    """A user took a seat they were not on before."""

    username: str
    seat_number: int


@dataclass(frozen=True)
class UserUnseatedEvent:
    """A user left the seat they were on."""

    username: str
    seat_number: int


@dataclass(frozen=True)
class UserSeatChangedEvent:
    """A user moved from one seat to another."""

    username: str
    old_seat: int
    new_seat: int


SeatDomainEvent = Union[UserSeatedEvent, UserUnseatedEvent, UserSeatChangedEvent]


def seat_change_event(change: SeatChange) -> SeatDomainEvent:
    """Map a roster-level :class:`SeatChange` onto its domain event."""
    if change.previous_seat is None:
        return UserSeatedEvent(username=change.username, seat_number=change.current_seat)
    if change.current_seat is None:
        return UserUnseatedEvent(username=change.username, seat_number=change.previous_seat)
    return UserSeatChangedEvent(
        username=change.username,
        old_seat=change.previous_seat,
        new_seat=change.current_seat,
    )
