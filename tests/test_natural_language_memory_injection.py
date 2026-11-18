import pytest
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
from ushareiplay.adapters.outbound.llm.natural_language_resolver import (
    OpenAICompatibleNaturalLanguageResolver,
)
from ushareiplay.modules.command.domain import NaturalLanguageResult
from ushareiplay.modules.command.use_cases import ResolveNaturalLanguage
from ushareiplay.modules.user.domain import MemorySettings
from ushareiplay.modules.user.use_cases import UserMemoryService
from tests.fakes.in_memory_chat_log_repository import InMemoryChatLogRepository
from tests.fakes.in_memory_memory_distiller import InMemoryMemoryDistiller
from tests.fakes.in_memory_user_memory_repository import InMemoryUserMemoryRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


def _use_case(config):
    return ResolveNaturalLanguage(OpenAICompatibleNaturalLanguageResolver(config), config)


def test_resolver_prompt_injection_with_memory_context():
    resolver = _use_case(
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
    resolver = _use_case(
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
async def test_dialogue_context_is_assembled_from_repositories():
    users = InMemoryUserRepository()
    memories = InMemoryUserMemoryRepository()
    chat_logs = InMemoryChatLogRepository(memories)
    service = UserMemoryService(
        users=users,
        memories=memories,
        chat_logs=chat_logs,
        distiller=InMemoryMemoryDistiller(),
        settings=MemorySettings(),
    )

    # User has no history initially
    ctx_empty = await service.dialogue_context("david")
    assert ctx_empty["directives"] == []
    assert ctx_empty["profile"] == ""
    assert ctx_empty["short_term_chats"] == []

    # Create user memory and logs
    user = await users.get_or_create("david")
    await memories.update(
        user.id,
        directives=["称谓: 大卫哥"],
        profile="喜欢电子乐",
        consolidated_at=datetime(2025, 1, 1),
    )
    await chat_logs.create(user.id, "放首电音")
    await chat_logs.create(user.id, "音量调大点")

    ctx_filled = await service.dialogue_context("david", user_level=20)
    assert ctx_filled["directives"] == ["称谓: 大卫哥"]
    assert ctx_filled["profile"] == "喜欢电子乐"
    assert ctx_filled["short_term_chats"] == ["放首电音", "音量调大点"]


@pytest.mark.asyncio
async def test_resolver_resolve_with_memory_context():
    resolver = _use_case(
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

    with patch.object(resolver._resolver, "_call_api", new_callable=AsyncMock) as mock_api:
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
