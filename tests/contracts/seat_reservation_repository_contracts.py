"""可复用的 `SeatReservationRepository` 契约场景。"""

from datetime import datetime, timedelta

from ushareiplay.modules.seat.domain import SeatReservation


async def assert_create_and_lookup(repo, user_id: int, username: str, user_level: int):
    now = datetime(2026, 1, 1, 10, 0, 0)
    created = await repo.create(user_id=user_id, seat_number=3, duration_hours=4, start_time=now)

    assert isinstance(created, SeatReservation)
    assert created.user_id == user_id
    assert created.username == username
    assert created.user_level == user_level
    assert created.seat_number == 3
    assert created.duration_hours == 4
    assert created.start_time == now

    by_user = await repo.get_by_user_id(user_id)
    assert by_user == created

    by_seat = await repo.get_by_seat_number(3)
    assert by_seat == created

    assert await repo.get_by_user_id(999999) is None
    assert await repo.get_by_seat_number(12) is None


async def assert_active_reservations_filters_expired(repo, user_id: int):
    now = datetime(2026, 1, 1, 12, 0, 0)
    await repo.create(
        user_id=user_id, seat_number=1, duration_hours=2, start_time=now - timedelta(hours=1)
    )
    await repo.create(
        user_id=user_id, seat_number=2, duration_hours=1, start_time=now - timedelta(hours=3)
    )

    active = await repo.get_active_reservations(now=now)
    assert [r.seat_number for r in active] == [1]


async def assert_update_start_time(repo, user_id: int):
    t1 = datetime(2026, 1, 1, 10, 0, 0)
    t2 = datetime(2026, 1, 1, 14, 0, 0)
    created = await repo.create(user_id=user_id, seat_number=5, duration_hours=2, start_time=t1)

    updated = await repo.update_start_time(created.id, t2)
    assert updated is not None
    assert updated.start_time == t2
    assert (await repo.get_by_seat_number(5)).start_time == t2

    assert await repo.update_start_time(999999, t2) is None


async def assert_remove_by_id_and_by_user(repo, user_id: int):
    r1 = await repo.create(user_id=user_id, seat_number=7, duration_hours=2)
    assert await repo.remove_by_id(r1.id) is True
    assert await repo.get_by_seat_number(7) is None
    assert await repo.remove_by_id(r1.id) is False

    await repo.create(user_id=user_id, seat_number=8, duration_hours=2)
    await repo.create(user_id=user_id, seat_number=9, duration_hours=2)
    assert await repo.remove_by_user_id(user_id) is True
    assert await repo.get_by_user_id(user_id) is None
