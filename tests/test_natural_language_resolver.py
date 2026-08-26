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
            type="reply", content="[智能] 你好呀！我是派对音乐助手~"
        )


@pytest.mark.asyncio
async def test_resolver_reply_already_tagged_is_idempotent(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
        }
    )

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"type": "reply", "content": "[智能] 已经在播放啦"}
                    )
                }
            }
        ]
    }

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = json.dumps(mock_response)
        result = await resolver.resolve(
            user_text="放歌了吗",
            user_name="Bob",
            user_level=0,
            commands_config=mock_commands_config,
        )

        assert result == NaturalLanguageResult(
            type="reply", content="[智能] 已经在播放啦"
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


@pytest.mark.asyncio
async def test_resolver_handles_thinking_model_tags(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
        }
    )

    content = (
        "<think>用户想听胡彦斌的潇湘雨。等级L1，输出 :play。\n"
        '{"type": "command", "content": ":play 潇湘雨 胡彦斌"}\n'
        "</think>\n\n"
        '{"type": "command", "content": ":play 潇湘雨 胡彦斌"}'
    )
    mock_response = {"choices": [{"message": {"content": content}}]}

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = json.dumps(mock_response)
        result = await resolver.resolve(
            user_text="来首胡彦斌的潇湘雨",
            user_name="Outlier",
            user_level=1,
            commands_config=mock_commands_config,
        )

        assert result == NaturalLanguageResult(
            type="command", content=":play 潇湘雨 胡彦斌"
        )


def test_resolver_injects_room_info_into_prompt(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
        }
    )

    room_info_host = {
        "is_guest_room": False,
        "room_id": "FM15321640",
        "user_count": 10,
        "focus_count": 4,
        "recommendation_enabled": True,
    }

    prompt_host = resolver._build_system_prompt(
        user_name="Alice",
        user_level=1,
        commands_config=mock_commands_config,
        room_info=room_info_host,
    )

    assert "主房间（宿主模式" in prompt_host
    assert "FM15321640" in prompt_host
    assert "10人" in prompt_host
    assert "4人" in prompt_host
    assert "派对推荐: 开启" in prompt_host

    room_info_guest = {
        "is_guest_room": True,
        "room_id": "FM999999",
        "user_count": 3,
        "focus_count": 0,
        "recommendation_enabled": False,
    }

    prompt_guest = resolver._build_system_prompt(
        user_name="Bob",
        user_level=1,
        commands_config=mock_commands_config,
        room_info=room_info_guest,
    )

    assert "他人房间（客房模式" in prompt_guest
    assert "FM999999" in prompt_guest
    assert "3人" in prompt_guest
    assert "派对推荐: 关闭" in prompt_guest


def test_resolver_injects_playback_and_playlist_info_into_prompt(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
        }
    )

    playback_info = {
        "song": "Fictional (Stripped)",
        "singer": "Khloe Rose",
        "player": "不约儿童🐏🐏",
        "playlist_name": "咿鸭咿鸭yo宝天天开心",
        "playlist_type": "歌单",
        "play_mode": "随机播放",
    }

    prompt = resolver._build_system_prompt(
        user_name="不约儿童🐏🐏",
        user_level=0,
        commands_config=mock_commands_config,
        playback_info=playback_info,
    )

    assert "当前正在播放歌曲: Fictional (Stripped) - Khloe Rose" in prompt
    assert "当前播放者/点歌人: 不约儿童🐏🐏" in prompt
    assert "当前播放列表/歌单: [歌单] 咿鸭咿鸭yo宝天天开心 (by 不约儿童🐏🐏)" in prompt
    assert "播放模式: 随机播放" in prompt
    assert "播我的歌单" in prompt or "歌单" in prompt


def test_resolver_prompt_when_no_active_playlist(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
        }
    )

    playback_info = {
        "song": "晴天",
        "singer": "周杰伦",
        "player": "Joyer",
    }

    prompt = resolver._build_system_prompt(
        user_name="Alice",
        user_level=1,
        commands_config=mock_commands_config,
        playback_info=playback_info,
    )

    assert "当前正在播放歌曲: 晴天 - 周杰伦" in prompt
    assert "当前播放者/点歌人: Joyer" in prompt
    assert "当前播放列表/歌单: 暂无活跃歌单" in prompt


@pytest.mark.asyncio
async def test_resolver_resolves_playlist_status_reply(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
        }
    )

    playback_info = {
        "song": "Fictional (Stripped)",
        "singer": "Khloe Rose",
        "player": "不约儿童🐏🐏",
        "playlist_name": "咿鸭咿鸭yo宝天天开心",
        "playlist_type": "歌单",
        "play_mode": "随机播放",
    }

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"type": "reply", "content": "是的，现在正在播放你的歌单《咿鸭咿鸭yo宝天天开心》哦~"}
                    )
                }
            }
        ]
    }

    with patch.object(resolver, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = json.dumps(mock_response)
        result = await resolver.resolve(
            user_text="现在是播我的歌单吗",
            user_name="不约儿童🐏🐏",
            user_level=0,
            commands_config=mock_commands_config,
            playback_info=playback_info,
        )

        assert result == NaturalLanguageResult(
            type="reply", content="[智能] 是的，现在正在播放你的歌单《咿鸭咿鸭yo宝天天开心》哦~"
        )


def test_resolver_prompt_with_system_user_timer(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
        }
    )

    playback_info = {
        "song": "稻香",
        "singer": "周杰伦",
        "player": "Timer",
        "playlist_name": "每日早安曲",
        "playlist_type": "歌单",
    }

    prompt = resolver._build_system_prompt(
        user_name="Alice",
        user_level=1,
        commands_config=mock_commands_config,
        playback_info=playback_info,
    )

    assert "当前播放者/点歌人: Timer (系统定时器自动播放)" in prompt
    assert "当前播放列表/歌单: [歌单] 每日早安曲 (by Timer [系统播放])" in prompt
    assert "若当前播放者是系统用户（如 Timer、Console、Agent 等系统角色）" in prompt


def test_resolver_prompt_with_system_user_console(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "system_users": ["Console", "CustomBot"],
        }
    )

    playback_info = {
        "song": "晴天",
        "singer": "周杰伦",
        "player": "Console",
    }

    prompt = resolver._build_system_prompt(
        user_name="Bob",
        user_level=1,
        commands_config=mock_commands_config,
        playback_info=playback_info,
    )

    assert "当前播放者/点歌人: Console (系统控制台/后台指令)" in prompt

    playback_info_custom = {
        "song": "晴天",
        "singer": "周杰伦",
        "player": "CustomBot",
    }
    prompt_custom = resolver._build_system_prompt(
        user_name="Bob",
        user_level=1,
        commands_config=mock_commands_config,
        playback_info=playback_info_custom,
    )
    assert "当前播放者/点歌人: CustomBot (系统自动化任务/非普通用户)" in prompt_custom


def test_resolver_custom_prompt_injection(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "system_prompt": "额外指令：请用俏皮可爱的语气回复，每句话结尾加上喵~",
        }
    )

    prompt = resolver._build_system_prompt(
        user_name="Alice",
        user_level=1,
        commands_config=mock_commands_config,
    )

    assert "【用户自定义行为指令 / 补充设定】" in prompt
    assert "额外指令：请用俏皮可爱的语气回复，每句话结尾加上喵~" in prompt


def test_resolver_custom_prompt_alias_key(mock_commands_config):
    resolver = NaturalLanguageResolver(
        config={
            "enabled": True,
            "api_key": "test-key",
            "custom_prompt": "自定义指令：保持专业简洁风格。",
        }
    )

    prompt = resolver._build_system_prompt(
        user_name="Alice",
        user_level=1,
        commands_config=mock_commands_config,
    )

    assert "【用户自定义行为指令 / 补充设定】" in prompt
    assert "自定义指令：保持专业简洁风格。" in prompt




