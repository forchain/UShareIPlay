import pytest
from datetime import datetime, timedelta
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO
from ushareiplay.dal.user_memory_dao import UserMemoryDAO
from ushareiplay.models.user import User
from ushareiplay.models.user_chat_log import UserChatLog
from ushareiplay.models.user_memory import UserMemory
from ushareiplay.core.chat_intake import ChatIntakeResult, ChatIntakeKind
from ushareiplay.managers.keyword_manager import KeywordManager


@pytest.mark.asyncio
async def test_user_chat_log_and_memory_crud():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        # Create chat log for user
        log1 = await UserChatLogDAO.create("alice", "你好群主，放首周杰伦的歌")
        assert log1.id is not None
        assert log1.content == "你好群主，放首周杰伦的歌"
        assert log1.created_at is not None

        # Verify user created
        user = await UserDAO.get_by_username("alice")
        assert user is not None
        assert log1.user_id == user.id

        # Create more logs
        await UserChatLogDAO.create("alice", "再放一首晴天")
        await UserChatLogDAO.create("alice", "谢谢群主")

        # Check count unconsolidated
        count = await UserChatLogDAO.count_unconsolidated(user.id)
        assert count == 3

        # Memory get_or_create
        memory, created = await UserMemoryDAO.get_or_create("alice")
        assert created is True
        assert memory.immutable_directives == []
        assert memory.profile_summary == ""
        assert memory.last_consolidated_at is None

        # Update memory
        now = datetime.now()
        updated_mem = await UserMemoryDAO.update_memory(
            user.id,
            directives=["称谓: 浩哥", "硬性偏好: 喜好周杰伦"],
            profile_summary="喜欢流行音乐和周杰伦",
            consolidated_at=now,
        )
        assert updated_mem.immutable_directives == ["称谓: 浩哥", "硬性偏好: 喜好周杰伦"]
        assert updated_mem.profile_summary == "喜欢流行音乐和周杰伦"
        assert updated_mem.last_consolidated_at == now

        # Add a new log after consolidation
        await UserChatLogDAO.create("alice", "新的聊天内容")
        count_after = await UserChatLogDAO.count_unconsolidated(user.id, since=now)
        assert count_after == 1

        unconsolidated_logs = await UserChatLogDAO.get_unconsolidated_logs(user.id, since=now)
        assert len(unconsolidated_logs) == 1
        assert unconsolidated_logs[0].content == "新的聊天内容"

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_canonical_user_memory_unification():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        # Create canonical user and alias user
        main_user = await User.create(username="bob_main", level=3)
        alias_user = await User.create(username="bob_alias", level=0, canonical_user=main_user)

        # Logging via alias should resolve to main user
        log = await UserChatLogDAO.create("bob_alias", "我换小号来了")
        assert log.user_id == main_user.id

        # Memory lookup via alias should resolve to main user
        memory, _ = await UserMemoryDAO.get_or_create("bob_alias")
        assert memory.user_id == main_user.id

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_active_user_ids_with_unconsolidated_logs():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        # User 1: 5 logs
        for i in range(5):
            await UserChatLogDAO.create("user_a", f"msg {i}")

        # User 2: 2 logs
        for i in range(2):
            await UserChatLogDAO.create("user_b", f"msg {i}")

        active_users_min_3 = await UserChatLogDAO.get_active_user_ids_with_unconsolidated_logs(min_count=3)
        assert len(active_users_min_3) == 1
        user_a = await UserDAO.get_by_username("user_a")
        assert active_users_min_3[0][0] == user_a.id
        assert active_users_min_3[0][1] == 5

        active_users_min_1 = await UserChatLogDAO.get_active_user_ids_with_unconsolidated_logs(min_count=1)
        assert len(active_users_min_1) == 2

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_keyword_manager_dispatch_mention_logs_chat(monkeypatch):
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not KeywordManager.is_initialized():
            KeywordManager.initialize()
        km = KeywordManager.instance()
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

        charlie_user = await UserDAO.get_by_username("charlie")
        assert charlie_user is not None
        logs = await UserChatLog.filter(user_id=charlie_user.id)
        assert len(logs) == 1
        assert logs[0].content == "周杰伦 晴天"

    finally:
        await db.close()
