from ushareiplay.managers.seat_manager.domain_events import (
    UserSeatChangedEvent,
    UserSeatedEvent,
    UserUnseatedEvent,
    seat_change_event,
)
from ushareiplay.managers.seat_manager.roster import SeatChange


def test_a_new_occupant_maps_to_a_seated_event():
    assert seat_change_event(SeatChange("Alice", None, 5)) == UserSeatedEvent("Alice", 5)


def test_a_departure_maps_to_an_unseated_event():
    assert seat_change_event(SeatChange("Alice", 5, None)) == UserUnseatedEvent("Alice", 5)


def test_a_move_maps_to_a_seat_changed_event():
    assert (
        seat_change_event(SeatChange("Alice", 3, 9))
        == UserSeatChangedEvent("Alice", 3, 9)
    )


def test_domain_events_are_named_after_their_classes():
    assert type(UserSeatedEvent("Alice", 1)).__name__ == "UserSeatedEvent"
    assert type(UserUnseatedEvent("Alice", 1)).__name__ == "UserUnseatedEvent"
    assert (
        type(UserSeatChangedEvent("Alice", 1, 2)).__name__ == "UserSeatChangedEvent"
    )
