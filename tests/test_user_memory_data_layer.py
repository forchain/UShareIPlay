import pytest
from datetime import datetime

from ushareiplay.adapters.outbound.persistence.chat_log_repository import (
    TortoiseChatLogRepository,
)
from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.models.user import User
from ushareiplay.adapters.outbound.persistence.user_memory_repository import (
    TortoiseUserMemoryRepository,
)
from ushareiplay.adapters.outbound.persistence.user_repository import (
    TortoiseUserRepository,
)
from ushareiplay.core.chat_intake import ChatIntakeResult, ChatIntakeKind
from ushareiplay.managers.keyword_manager import KeywordManager
from tests.fakes.in_memory_memory_distiller import InMemoryMemoryDistiller


def _stack():
    users = TortoiseUserRepository()
    memories = TortoiseUserMemoryRepository()
    chat_logs = TortoiseChatLogRepository()
    return users, memories, chat_logs


@pytest.mark.asyncio
async def test_user_chat_log_and_memory_crud():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        users, memories, chat_logs = _stack()

        # Create chat log for user
        alice = await users.get_or_create("alice")
        log1 = await chat_logs.create(alice.id, "你好群主，放首周杰伦的歌")
        assert log1.id is not None
        assert log1.content == "你好群主，放首周杰伦的歌"
        assert log1.created_at is not None
        assert log1.user_id == alice.id

        # Create more logs
        await chat_logs.create(alice.id, "再放一首晴天")
        await chat_logs.create(alice.id, "谢谢群主")

        # Check count unconsolidated
        count = await chat_logs.count_unconsolidated(alice.id)
        assert count == 3

        # Memory is absent until the first consolidation
        assert await memories.get(alice.id) is None

        # Update memory
        now = datetime.now()
        updated_mem = await memories.update(
            alice.id,
            directives=["称谓: 浩哥", "硬性偏好: 喜好周杰伦"],
            profile="喜欢流行音乐和周杰伦",
            consolidated_at=now,
        )
        assert updated_mem.directives == ["称谓: 浩哥", "硬性偏好: 喜好周杰伦"]
        assert updated_mem.profile == "喜欢流行音乐和周杰伦"
        assert updated_mem.last_consolidated_at == now

        # Add a new log after consolidation
        await chat_logs.create(alice.id, "新的聊天内容")
        count_after = await chat_logs.count_unconsolidated(alice.id, since=now)
        assert count_after == 1

        unconsolidated_logs = await chat_logs.unconsolidated_logs(alice.id, since=now)
        assert len(unconsolidated_logs) == 1
        assert unconsolidated_logs[0].content == "新的聊天内容"

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_canonical_user_memory_unification():
    from ushareiplay.modules.user.domain import MemorySettings
    from ushareiplay.modules.user.use_cases import UserMemoryService

    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        users, memories, chat_logs = _stack()
        service = UserMemoryService(
            users=users,
            memories=memories,
            chat_logs=chat_logs,
            distiller=InMemoryMemoryDistiller(),
            settings=MemorySettings(),
        )

        # Create canonical user and alias user
        main_user = await User.create(username="bob_main", level=3)
        await User.create(username="bob_alias", level=0, canonical_user=main_user)

        # Logging via alias should resolve to main user
        log = await service.record_chat("bob_alias", "我换小号来了")
        assert log.user_id == main_user.id

        # Memory lookup via alias should resolve to main user
        context = await service.dialogue_context("bob_alias", user_level=20)
        assert [chat for chat in context["short_term_chats"]] == ["我换小号来了"]
        assert await memories.get(main_user.id) is None

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_active_user_ids_with_unconsolidated_logs():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        users, _memories, chat_logs = _stack()

        # User 1: 5 logs
        user_a = await users.get_or_create("user_a")
        for i in range(5):
            await chat_logs.create(user_a.id, f"msg {i}")

        # User 2: 2 logs
        user_b = await users.get_or_create("user_b")
        for i in range(2):
            await chat_logs.create(user_b.id, f"msg {i}")

        active_users_min_3 = await chat_logs.active_user_ids_with_unconsolidated_logs(
            min_count=3
        )
        assert len(active_users_min_3) == 1
        assert active_users_min_3[0][0] == user_a.id
        assert active_users_min_3[0][1] == 5

        active_users_min_1 = await chat_logs.active_user_ids_with_unconsolidated_logs(
            min_count=1
        )
        assert len(active_users_min_1) == 2

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_keyword_manager_dispatch_mention_logs_chat(monkeypatch):
    from ushareiplay.modules.user.domain import MemorySettings
    from ushareiplay.modules.user.use_cases import UserMemoryService

    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        users, memories, chat_logs = _stack()
        if not KeywordManager.is_initialized():
            KeywordManager.initialize()
        km = KeywordManager.instance()
        km.user_memory = UserMemoryService(
            users=users,
            memories=memories,
            chat_logs=chat_logs,
            distiller=InMemoryMemoryDistiller(),
            settings=MemorySettings(),
        )
        # Mock nl resolver and execute_keyword to avoid external calls

        async def dummy_resolve(*args, **kwargs):
            return True
        monkeypatch.setattr(km, "_resolve_natural_language", dummy_resolve)

        result = ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="charlie",
            text="周杰伦",
            params="晴天",
            raw="souler[charlie]说: @我 周杰伦 晴天",
        )
        await km.dispatch_mention(result)

        charlie_user = await users.get_by_username("charlie")
        assert charlie_user is not None
        logs = await chat_logs.unconsolidated_logs(charlie_user.id)
        assert len(logs) == 1
        assert logs[0].content == "周杰伦 晴天"

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_user_memory_immutable_directives_stored_as_utf8_json():
    from tortoise import Tortoise

    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        users, memories, _chat_logs = _stack()
        user = await users.get_or_create("diana")
        await memories.update(
            user.id,
            directives=["称谓: 浩哥", "硬性偏好: 喜好周杰伦"],
            profile="喜欢流行音乐和周杰伦",
            consolidated_at=datetime(2026, 1, 1),
        )

        conn = Tortoise.get_connection("default")
        rows = await conn.execute_query_dict(
            "SELECT immutable_directives, profile_summary FROM user_memories WHERE user_id = ?",
            [user.id],
        )
        assert len(rows) == 1
        raw_directives = rows[0]["immutable_directives"]

        # Verify directives are stored as literal UTF-8 JSON and not escaped \uXXXX
        assert raw_directives == '["称谓: 浩哥","硬性偏好: 喜好周杰伦"]'
        assert "\\u" not in raw_directives

        # Verify reading back through the repository
        memory = await memories.get(user.id)
        assert memory is not None
        assert memory.directives == ["称谓: 浩哥", "硬性偏好: 喜好周杰伦"]
        assert memory.profile == "喜欢流行音乐和周杰伦"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_user_memory_legacy_escaped_unicode_backward_compatibility():
    from tortoise import Tortoise

    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        users, memories, _chat_logs = _stack()
        user = await users.get_or_create("edward")
        conn = Tortoise.get_connection("default")

        # Simulate legacy record stored with escaped unicode
        legacy_raw = '["\\u79f0\\u8c13: \\u6d69\\u54e5"]'
        await conn.execute_query(
            "INSERT INTO user_memories (user_id, immutable_directives, profile_summary, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            [user.id, legacy_raw, "旧画像"],
        )

        # Verify legacy record is transparently loaded
        memory = await memories.get(user.id)
        assert memory is not None
        assert memory.directives == ["称谓: 浩哥"]
        assert memory.profile == "旧画像"

        # Update memory and verify it is rewritten as unescaped UTF-8 JSON
        await memories.update(
            user.id,
            directives=["称谓: 浩哥", "新规: 禁点慢歌"],
            profile="旧画像",
            consolidated_at=datetime(2026, 1, 1),
        )
        rows = await conn.execute_query_dict(
            "SELECT immutable_directives FROM user_memories WHERE user_id = ?",
            [user.id],
        )
        assert rows[0]["immutable_directives"] == '["称谓: 浩哥","新规: 禁点慢歌"]'
        assert "\\u" not in rows[0]["immutable_directives"]
    finally:
        await db.close()
