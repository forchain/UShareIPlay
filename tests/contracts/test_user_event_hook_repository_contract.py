import pytest_asyncio

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.user_event_hook_repository import (
    TortoiseUserEventHookRepository,
)
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from tests.contracts import user_event_hook_repository_contracts as contracts
from tests.fakes.in_memory_user_event_hook_repository import InMemoryUserEventHookRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


@pytest_asyncio.fixture(params=["in_memory", "sqlite"])
async def repository_and_users(request):
    if request.param == "in_memory":
        users = InMemoryUserRepository()
        yield InMemoryUserEventHookRepository(users=users), users
        return

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    try:
        users = TortoiseUserRepository()
        yield TortoiseUserEventHookRepository(users=users), users
    finally:
        await manager.close()


async def test_crud_across_event_types(repository_and_users):
    repository, users = repository_and_users
    await contracts.assert_crud_across_event_types(repository, users)


async def test_delete_all_by_username(repository_and_users):
    repository, users = repository_and_users
    await contracts.assert_delete_all_by_username(repository, users)


async def test_get_all_ordered_returns_every_row(repository_and_users):
    repository, users = repository_and_users
    await contracts.assert_get_all_ordered_returns_every_row(repository, users)


async def test_event_types_do_not_share_rows(repository_and_users):
    repository, users = repository_and_users
    await contracts.assert_event_types_do_not_share_rows(repository, users)


async def test_receive_resolves_alias_group(repository_and_users):
    repository, users = repository_and_users
    await contracts.assert_receive_resolves_alias_group(repository, users)


async def test_alias_group_covers_rows_bound_to_an_alias_id(repository_and_users):
    repository, users = repository_and_users
    await contracts.assert_alias_group_covers_rows_bound_to_an_alias_id(repository, users)


async def test_single_id_resolution_stays_on_the_canonical_id(repository_and_users):
    repository, users = repository_and_users
    await contracts.assert_single_id_resolution_stays_on_the_canonical_id(repository, users)
