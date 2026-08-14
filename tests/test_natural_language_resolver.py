import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ushareiplay.core.natural_language_resolver import (
    NaturalLanguageResolver,
    NaturalLanguageResult,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_commands_config():
    return [
        {
            "prefix": "play",
            "level": 1,
            "response_template": "{song} - {singer}",
            "description": "播放指定歌曲",
        },
        {
            "prefix": "next",
            "level": 0,
            "description": "切下一首歌",
        },
        {
            "prefix": "vol",
            "level": 1,
            "description": "调整音量 0-100",
        },
        {
            "prefix": "admin",
            "level": 9,
            "description": "设置或取消管理员",
        },
    ]


def test_resolver_disabled_returns_none(mock_commands_config):
    resolver = NaturalLanguageResolver(config={"enabled": False})
    result = _run(
        resolver.resolve(
            user_text="放首晴天",
            user_name="Alice",
            user_level=1,
            commands_config=mock_commands_config,
        )
    )
    assert result is None


def test_resolver_missing_api_key_returns_none(mock_commands_config):
    resolver = NaturalLanguageResolver(config={"enabled": True, "api_key": ""})
    result = _run(
        resolver.resolve(
            user_text="放首晴天",
            user_name="Alice",
            user_level=1,
            commands_config=mock_commands_config,
        )
    )
    assert result is None


@pytest.mark.asyncio
async def test_resolver_success_command(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        }
    )

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"type": "command", "content": ":play 周杰伦 晴天"})
                }
            }
        ]
    }

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = json.dumps(mock_response)
        result = await resolver.resolve(
            user_text="帮我放一首周杰伦的晴天",
            user_name="Alice",
            user_level=1,
            commands_config=mock_commands_config,
            playback_info={"song": "稻香", "singer": "周杰伦"},
        )

        assert result == NaturalLanguageResult(type="command", content=":play 周杰伦 晴天")


@pytest.mark.asyncio
async def test_resolver_success_reply(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        }
    )

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"type": "reply", "content": "你好呀！我是派对音乐助手~"}
                    )
                }
            }
        ]
    }

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = json.dumps(mock_response)
        result = await resolver.resolve(
            user_text="你好呀",
            user_name="Bob",
            user_level=0,
            commands_config=mock_commands_config,
        )

        assert result == NaturalLanguageResult(
            type="reply", content="你好呀！我是派对音乐助手~"
        )


@pytest.mark.asyncio
async def test_resolver_handles_markdown_wrapped_json(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
        }
    )

    content = "```json\n{\"type\": \"command\", \"content\": \":next\"}\n```"
    mock_response = {"choices": [{"message": {"content": content}}]}

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = json.dumps(mock_response)
        result = await resolver.resolve(
            user_text="切歌",
            user_name="Charlie",
            user_level=0,
            commands_config=mock_commands_config,
        )

        assert result == NaturalLanguageResult(type="command", content=":next")


@pytest.mark.asyncio
async def test_resolver_handles_api_exception(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
        }
    )

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = TimeoutError("Request timed out")
        result = await resolver.resolve(
            user_text="放歌",
            user_name="David",
            user_level=1,
            commands_config=mock_commands_config,
        )

        assert result is None


@pytest.mark.asyncio
async def test_resolver_handles_malformed_json(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
        }
    )

    mock_response = {"choices": [{"message": {"content": "Not a json response"}}]}

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = json.dumps(mock_response)
        result = await resolver.resolve(
            user_text="放歌",
            user_name="David",
            user_level=1,
            commands_config=mock_commands_config,
        )

        assert result is None
