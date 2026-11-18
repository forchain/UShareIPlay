import pytest_asyncio

from tests.contracts import seat_reservation_repository_contracts as contracts
from tests.fakes.in_memory_seat_reservation_repository import InMemorySeatReservationRepository
from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.models.user import User as UserModel
from ushareiplay.adapters.outbound.persistence.seat_reservation_repository import (
    TortoiseSeatReservationRepository,
)


@pytest_asyncio.fixture(params=["in_memory", "sqlite"])
async def seat_reservation_env(request):
    if request.param == "in_memory":
        repo = InMemorySeatReservationRepository()
        repo.seed_user(1, "Alice", level=3)
        yield repo, 1, "Alice", 3
        return

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    try:
        user = await UserModel.create(username="Alice", level=3)
        yield TortoiseSeatReservationRepository(), user.id, "Alice", 3
    finally:
        await manager.close()


async def test_create_and_lookup(seat_reservation_env):
    repo, uid, uname, lvl = seat_reservation_env
    await contracts.assert_create_and_lookup(repo, uid, uname, lvl)


async def test_active_reservations_filters_expired(seat_reservation_env):
    repo, uid, _uname, _lvl = seat_reservation_env
    await contracts.assert_active_reservations_filters_expired(repo, uid)


async def test_update_start_time(seat_reservation_env):
    repo, uid, _uname, _lvl = seat_reservation_env
    await contracts.assert_update_start_time(repo, uid)


async def test_remove_by_id_and_by_user(seat_reservation_env):
    repo, uid, _uname, _lvl = seat_reservation_env
    await contracts.assert_remove_by_id_and_by_user(repo, uid)
