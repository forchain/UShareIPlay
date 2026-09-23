import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.dal.user_memory_dao import UserMemoryDAO
from ushareiplay.managers.memory_manager import MemoryManager


@pytest.mark.asyncio
async def test_consolidation_below_threshold_skips_llm():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True, "min_messages": 10}}})

        # Add only 5 messages (below 10)
        for i in range(5):
            await UserChatLogDAO.create("alice", f"消息 {i}")

        with patch.object(mm, "_call_consolidation_llm", new_callable=AsyncMock) as mock_llm:
            result = await mm._consolidate_single_user("alice")
            assert result is False
            mock_llm.assert_not_called()

        memory = await UserMemoryDAO.get_by_username("alice")
        # Memory should not have any cursor advanced
        assert memory is None or memory.last_consolidated_at is None

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_consolidation_success_advances_cursor_and_updates_memory():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True, "min_messages": 5}}})

        user = await UserDAO.get_or_create("bob")
        await UserMemoryDAO.update_memory(
            user.id,
            directives=["称谓: 浩哥"],
            profile_summary="喜欢华语流行",
        )

        for i in range(5):
            await UserChatLogDAO.create("bob", f"今天想听摇滚 {i}")

        mock_updated_directives = ["称谓: 浩哥", "硬性偏好: 喜好摇滚乐"]
        mock_updated_profile = "喜欢华语流行与摇滚乐，经常点快节奏歌曲"

        with patch.object(mm, "_call_consolidation_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (True, mock_updated_directives, mock_updated_profile)
            result = await mm._consolidate_single_user("bob")
            assert result is True
            assert mock_llm.call_count == 1

        memory = await UserMemoryDAO.get_by_username("bob")
        assert memory is not None
        assert memory.immutable_directives == mock_updated_directives
        assert memory.profile_summary == mock_updated_profile
        assert memory.last_consolidated_at is not None

        # After consolidation, unconsolidated count should be 0
        remaining = await UserChatLogDAO.count_unconsolidated(user.id, since=memory.last_consolidated_at)
        assert remaining == 0

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_consolidation_failure_retains_cursor():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True, "min_messages": 3}}})

        user = await UserDAO.get_or_create("charlie")
        original_time = datetime(2026, 1, 1, 12, 0, 0)
        await UserMemoryDAO.update_memory(
            user.id,
            directives=["称谓: 查理"],
            profile_summary="老用户",
            consolidated_at=original_time,
        )

        for i in range(4):
            await UserChatLogDAO.create("charlie", f"新消息 {i}")

        with patch.object(mm, "_call_consolidation_llm", new_callable=AsyncMock) as mock_llm:
            # Simulate LLM failure (e.g. timeout / error)
            mock_llm.return_value = (False, ["称谓: 查理"], "老用户")
            result = await mm._consolidate_single_user("charlie")
            assert result is False

        # Verify cursor did not move
        memory = await UserMemoryDAO.get_by_username("charlie")
        assert memory.last_consolidated_at == original_time
        assert memory.immutable_directives == ["称谓: 查理"]

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_global_sweep_consolidates_all_eligible_users():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True, "min_messages": 3, "worker_delay_seconds": 0}}})

        # User 1: 4 messages (eligible)
        for i in range(4):
            await UserChatLogDAO.create("user_1", f"u1 msg {i}")

        # User 2: 1 message (ineligible)
        await UserChatLogDAO.create("user_2", "u2 msg 0")

        # User 3: 5 messages (eligible)
        for i in range(5):
            await UserChatLogDAO.create("user_3", f"u3 msg {i}")

        consolidated_users = []

        async def mock_single_user(username):
            consolidated_users.append(username)
            return True

        with patch.object(mm, "_consolidate_single_user", side_effect=mock_single_user):
            await mm._consolidate_all_eligible_users()

        assert "user_1" in consolidated_users
        assert "user_3" in consolidated_users
        assert "user_2" not in consolidated_users

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_memory_manager_worker_loop_and_debouncing():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True, "worker_delay_seconds": 0.01}}})
        mm._debounce_interval = 2.0  # 2 seconds for test

        await mm.start()

        processed_tasks = []

        async def mock_consolidate(username):
            processed_tasks.append(username)
            return True

        with patch.object(mm, "_consolidate_single_user", side_effect=mock_consolidate):
            # First schedule
            mm.schedule_consolidation_user("david")
            # Rapid second schedule should be debounced
            mm.schedule_consolidation_user("david")

            await asyncio.sleep(0.1)
            assert len(processed_tasks) == 1
            assert processed_tasks[0] == "david"

        await mm.stop()

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_memory_manager_timeout_configuration_and_forwarding():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()

        # 1. Default timeout should be 30.0s
        mm.configure({"llm": {"memory": {"enabled": True}}})
        assert mm.timeout == 30.0

        # 2. Configured custom timeout
        mm.configure({"llm": {"memory": {"enabled": True, "timeout": 45.0}}})
        assert mm.timeout == 45.0

        # 3. Verify _call_consolidation_llm passes timeout to resolver._call_api
        from ushareiplay.managers.keyword_manager import KeywordManager
        if not KeywordManager.is_initialized():
            KeywordManager.initialize()
        km = KeywordManager.instance()
        km._config = {
            "llm": {
                "enabled": True,
                "api_key": "test-key",
                "model": "deepseek-chat",
                "memory": {"enabled": True, "timeout": 45.0},
            }
        }
        # Reset resolver to pick up new config
        km._nl_resolver = None


        mock_llm_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"directives": ["称谓: 浩哥"], "profile": "喜欢流行"})
                    }
                }
            ]
        }

        with patch.object(km.nl_resolver, "_call_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = json.dumps(mock_llm_response)
            success, directives, profile = await mm._call_consolidation_llm(
                user_name="test_user",
                existing_directives=[],
                existing_profile="",
                new_messages=["消息1", "消息2"],
            )
            assert success is True
            assert directives == ["称谓: 浩哥"]
            assert profile == "喜欢流行"
            # Verify _call_api was called with timeout=45.0
            mock_api.assert_called_once()
            assert mock_api.call_args[1].get("timeout") == 45.0

    finally:
        await db.close()

