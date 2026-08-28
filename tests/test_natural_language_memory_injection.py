import pytest
import json
from unittest.mock import AsyncMock, patch
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.natural_language_resolver import (
    NaturalLanguageResolver,
    NaturalLanguageResult,
)
from ushareiplay.managers.memory_manager import MemoryManager
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO
from ushareiplay.dal.user_memory_dao import UserMemoryDAO


def test_resolver_prompt_injection_with_memory_context():
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
        }
    )

    memory_context = {
        "directives": ["称谓: 浩哥", "硬性偏好: 喜好周杰伦与摇滚"],
        "profile": "常在深夜来房间听歌，性格随和活跃",
        "short_term_chats": ["刚才那首是什么", "今天推荐点快歌"],
    }

    prompt = resolver._build_system_prompt(
        user_name="Alice",
        user_level=1,
        commands_config=[{"prefix": "play", "level": 1, "description": "播放歌曲"}],
        memory_context=memory_context,
    )

    assert "【用户长期记忆与核心设定 (铁律区 - 必须严格遵守)】" in prompt
    assert "* 称谓: 浩哥" in prompt
    assert "* 硬性偏好: 喜好周杰伦与摇滚" in prompt
    assert "- 用户画像与偏好特点:" in prompt
    assert "常在深夜来房间听歌，性格随和活跃" in prompt
    assert "【近期临时对话记录（短期记忆）】" in prompt
    assert "- 用户发言: 刚才那首是什么" in prompt
    assert "- 用户发言: 今天推荐点快歌" in prompt
    assert "回复中必须严格遵守铁律区中的用户称谓与偏好设定" in prompt


def test_resolver_prompt_without_memory_context():
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
        }
    )

    prompt = resolver._build_system_prompt(
        user_name="Bob",
        user_level=1,
        commands_config=[{"prefix": "play", "level": 1, "description": "播放歌曲"}],
        memory_context=None,
    )

    assert "【用户长期记忆与核心设定 (铁律区 - 必须严格遵守)】" not in prompt
    assert "【近期临时对话记录（短期记忆）】" not in prompt



@pytest.mark.asyncio
async def test_memory_manager_get_user_dialogue_context():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True}}})

        # User has no history initially
        ctx_empty = await mm.get_user_dialogue_context("david")
        assert ctx_empty["directives"] == []
        assert ctx_empty["profile"] == ""
        assert ctx_empty["short_term_chats"] == []

        # Create user memory and logs
        user = await UserDAO.get_or_create("david")
        await UserMemoryDAO.update_memory(
            user_id=user.id,
            directives=["称谓: 大卫哥"],
            profile_summary="喜欢电子乐",
        )
        await UserChatLogDAO.create("david", "放首电音")
        await UserChatLogDAO.create("david", "音量调大点")

        ctx_filled = await mm.get_user_dialogue_context("david")
        assert ctx_filled["directives"] == ["称谓: 大卫哥"]
        assert ctx_filled["profile"] == "喜欢电子乐"
        assert ctx_filled["short_term_chats"] == ["放首电音", "音量调大点"]

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_resolver_resolve_with_memory_context():
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
        }
    )

    memory_context = {
        "directives": ["称谓: 浩哥"],
        "profile": "喜欢周杰伦",
        "short_term_chats": ["放首歌"],
    }

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"type": "reply", "content": "浩哥好，马上为您播放！"}
                    )
                }
            }
        ]
    }

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = json.dumps(mock_response)
        result = await resolver.resolve(
            user_text="你好呀",
            user_name="浩哥",
            user_level=1,
            memory_context=memory_context,
        )

        assert result == NaturalLanguageResult(
            type="reply", content="[智能] 浩哥好，马上为您播放！"
        )
        # Verify prompt received by API contained memory context
        payload = mock_api.call_args[0][0]
        system_msg = payload["messages"][0]["content"]
        assert "* 称谓: 浩哥" in system_msg
        assert "喜欢周杰伦" in system_msg
        assert "- 用户发言: 放首歌" in system_msg
