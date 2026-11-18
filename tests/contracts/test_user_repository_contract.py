import pytest_asyncio

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from tests.contracts import user_repository_contracts as contracts
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


@pytest_asyncio.fixture(params=["in_memory", "sqlite"])
async def user_repository(request):
    if request.param == "in_memory":
        yield InMemoryUserRepository()
        return

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    try:
        yield TortoiseUserRepository()
    finally:
        await manager.close()


async def test_get_or_create_is_idempotent(user_repository):
    await contracts.assert_get_or_create_is_idempotent(user_repository)


async def test_alias_resolves_to_canonical(user_repository):
    await contracts.assert_alias_resolves_to_canonical(user_repository)


async def test_resolve_canonical_follows_chain_and_falls_back(user_repository):
    await contracts.assert_resolve_canonical_follows_chain_and_falls_back(user_repository)


async def test_update_level(user_repository):
    await contracts.assert_update_level(user_repository)


async def test_update_level_if_lower(user_repository):
    await contracts.assert_update_level_if_lower(user_repository)


async def test_record_owner_gift(user_repository):
    await contracts.assert_record_owner_gift(user_repository)


async def test_record_heat_contribution(user_repository):
    await contracts.assert_record_heat_contribution(user_repository)


async def test_heat_accumulates_on_canonical(user_repository):
    await contracts.assert_heat_accumulates_on_canonical(user_repository)


async def test_identity_usernames(user_repository):
    await contracts.assert_identity_usernames(user_repository)


async def test_avatar_and_associated_ids(user_repository):
    await contracts.assert_avatar_and_associated_ids(user_repository)
