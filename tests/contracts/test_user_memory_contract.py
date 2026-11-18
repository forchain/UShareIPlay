"""`UserMemoryRepository` / `ChatLogRepository` 的契约：内存替身与 SQLite 各跑一遍。"""

import pytest_asyncio

from ushareiplay.adapters.outbound.persistence.chat_log_repository import (
    TortoiseChatLogRepository,
)
from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.user_memory_repository import (
    TortoiseUserMemoryRepository,
)
from ushareiplay.adapters.outbound.persistence.user_repository import (
    TortoiseUserRepository,
)
from tests.contracts import user_memory_contracts as contracts
from tests.fakes.in_memory_chat_log_repository import InMemoryChatLogRepository
from tests.fakes.in_memory_user_memory_repository import InMemoryUserMemoryRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


@pytest_asyncio.fixture(params=["in_memory", "sqlite"])
async def repositories(request):
    if request.param == "in_memory":
        users = InMemoryUserRepository()
        memories = InMemoryUserMemoryRepository()
        yield users, memories, InMemoryChatLogRepository(memories)
        return

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    try:
        yield (
            TortoiseUserRepository(),
            TortoiseUserMemoryRepository(),
            TortoiseChatLogRepository(),
        )
    finally:
        await manager.close()


async def test_memory_is_absent_until_written(repositories):
    users, memories, _chat_logs = repositories
    user = await users.get_or_create("alice")
    await contracts.assert_memory_is_absent_until_written(memories, user.id)


async def test_memory_update_creates_and_overwrites(repositories):
    users, memories, _chat_logs = repositories
    user = await users.get_or_create("alice")
    other = await users.get_or_create("bob")
    await contracts.assert_memory_update_creates_and_overwrites(memories, other.id, user.id)


async def test_chat_logs_record_in_order_and_count_since(repositories):
    users, _memories, chat_logs = repositories
    user = await users.get_or_create("alice")
    await contracts.assert_chat_logs_record_in_order_and_count_since(chat_logs, user.id)


async def test_chat_logs_are_ordered_and_limited(repositories):
    users, _memories, chat_logs = repositories
    user = await users.get_or_create("alice")
    await contracts.assert_chat_logs_are_ordered_and_limited(chat_logs, user.id)


async def test_global_sweep_respects_min_count_and_cursor(repositories):
    users, memories, chat_logs = repositories
    user_one = await users.get_or_create("alice")
    user_two = await users.get_or_create("bob")
    await contracts.assert_global_sweep_respects_min_count_and_cursor(
        chat_logs, memories, user_one.id, user_two.id
    )
