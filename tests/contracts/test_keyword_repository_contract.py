import pytest_asyncio

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.keyword_repository import (
    TortoiseKeywordRepository,
)
from ushareiplay.adapters.outbound.persistence.user_repository import (
    TortoiseUserRepository,
)
from tests.contracts import keyword_repository_contracts as contracts
from tests.fakes.in_memory_keyword_repository import InMemoryKeywordRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


@pytest_asyncio.fixture(params=["in_memory", "sqlite"])
async def keyword_repository(request):
    if request.param == "in_memory":
        users = InMemoryUserRepository()
        yield InMemoryKeywordRepository(users), users
        return

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    try:
        users = TortoiseUserRepository()
        yield TortoiseKeywordRepository(users), users
    finally:
        await manager.close()


async def test_create_and_get(keyword_repository):
    repository, users = keyword_repository
    await contracts.assert_create_and_get(repository, users)


async def test_get_by_keyword_and_username(keyword_repository):
    repository, users = keyword_repository
    await contracts.assert_get_by_keyword_and_username(repository, users)


async def test_find_accessible_keyword(keyword_repository):
    repository, users = keyword_repository
    await contracts.assert_find_accessible_keyword(repository, users)


async def test_grant_and_revoke_filter_ids(keyword_repository):
    repository, users = keyword_repository
    await contracts.assert_grant_and_revoke_filter_ids(repository, users)


async def test_update_publicity(keyword_repository):
    repository, users = keyword_repository
    await contracts.assert_update_publicity(repository, users)


async def test_delete(keyword_repository):
    repository, users = keyword_repository
    await contracts.assert_delete(repository, users)


async def test_delete_config_keywords(keyword_repository):
    repository, users = keyword_repository
    await contracts.assert_delete_config_keywords(repository, users)


async def test_lists(keyword_repository):
    repository, users = keyword_repository
    await contracts.assert_lists(repository, users)
