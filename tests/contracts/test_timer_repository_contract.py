import pytest_asyncio

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.timer_repository import TortoiseTimerRepository
from tests.contracts import repository_contracts as contracts
from tests.fakes.in_memory_timer_repository import InMemoryTimerRepository


@pytest_asyncio.fixture(params=["in_memory", "sqlite"])
async def timer_repository(request):
    if request.param == "in_memory":
        yield InMemoryTimerRepository()
        return

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    try:
        yield TortoiseTimerRepository()
    finally:
        await manager.close()


async def test_create_and_get(timer_repository):
    await contracts.assert_create_and_get(timer_repository)


async def test_get_or_create_is_idempotent(timer_repository):
    await contracts.assert_get_or_create_is_idempotent(timer_repository)


async def test_list_all(timer_repository):
    await contracts.assert_list_all(timer_repository)


async def test_update_enabled_and_next_trigger(timer_repository):
    await contracts.assert_update_enabled_and_next_trigger(timer_repository)


async def test_delete(timer_repository):
    await contracts.assert_delete(timer_repository)


async def test_count(timer_repository):
    await contracts.assert_count(timer_repository)


async def test_create_rejects_duplicate_key(timer_repository):
    await contracts.assert_create_rejects_duplicate_key(timer_repository)


async def test_prepare_is_idempotent(timer_repository):
    await contracts.assert_prepare_is_idempotent(timer_repository)
