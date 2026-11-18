"""Resolve-natural-language use case driven by an in-memory resolver port."""

import pytest

from ushareiplay.modules.command.domain import (
    NaturalLanguageContext,
    NaturalLanguageResult,
)
from ushareiplay.modules.command.use_cases import ResolveNaturalLanguage


class InMemoryNaturalLanguageResolver:
    """Records requests; returns the preset result or raises the preset error."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[tuple[str, NaturalLanguageContext]] = []

    async def resolve(self, text, context):
        self.calls.append((text, context))
        if self.error is not None:
            raise self.error
        return self.result


COMMANDS = [
    {"prefix": "play", "level": 1, "description": "播放指定歌曲"},
    {"prefix": "next", "level": 0, "description": "切下一首歌"},
]


def _use_case(resolver, **config):
    cfg = {"enabled": True, "api_key": "test-key", **config}
    return ResolveNaturalLanguage(resolver, cfg)


@pytest.mark.asyncio
async def test_disabled_resolver_skips_the_port():
    port = InMemoryNaturalLanguageResolver()
    use_case = ResolveNaturalLanguage(port, {"enabled": False})

    assert await use_case.resolve(user_text="放首晴天", user_name="Alice") is None
    assert port.calls == []


@pytest.mark.asyncio
async def test_missing_api_key_skips_the_port():
    port = InMemoryNaturalLanguageResolver()
    use_case = ResolveNaturalLanguage(port, {"enabled": True, "api_key": ""})

    assert await use_case.resolve(user_text="放首晴天", user_name="Alice") is None
    assert port.calls == []


@pytest.mark.asyncio
async def test_empty_text_skips_the_port():
    port = InMemoryNaturalLanguageResolver()
    use_case = _use_case(port)

    assert await use_case.resolve(user_text="", user_name="Alice") is None
    assert port.calls == []


@pytest.mark.asyncio
async def test_result_from_port_is_returned_unchanged():
    expected = NaturalLanguageResult(type="command", content=":play 周杰伦 晴天")
    port = InMemoryNaturalLanguageResolver(result=expected)
    use_case = _use_case(port, model="gpt-4o-mini", timeout=7.0)

    result = await use_case.resolve(
        user_text="帮我放一首周杰伦的晴天",
        user_name="Alice",
        user_level=1,
        commands_config=COMMANDS,
    )

    assert result is expected
    text, context = port.calls[0]
    assert text == "帮我放一首周杰伦的晴天"
    assert isinstance(context, NaturalLanguageContext)
    assert context.model == "gpt-4o-mini"
    assert context.timeout == 7.0
    assert "- 发言用户: Alice" in context.system_prompt
    assert "用户权限等级: L1" in context.system_prompt
    assert "`:play` (所需等级: L1): 播放指定歌曲" in context.system_prompt


@pytest.mark.asyncio
async def test_prompt_context_includes_room_playback_and_memory():
    port = InMemoryNaturalLanguageResolver()
    use_case = _use_case(port)

    await use_case.resolve(
        user_text="现在是播我的歌单吗",
        user_name="Bob",
        user_level=0,
        commands_config=COMMANDS,
        playback_info={
            "song": "晴天",
            "singer": "周杰伦",
            "player": "Timer",
            "playlist_name": "每日早安曲",
            "playlist_type": "歌单",
        },
        room_info={"is_guest_room": True, "room_id": "FM999999", "user_count": 3},
        memory_context={"directives": ["称谓: 浩哥"], "profile": "喜欢周杰伦"},
    )

    prompt = port.calls[0][1].system_prompt
    assert "当前播放者/点歌人: Timer (系统定时器自动播放)" in prompt
    assert "他人房间（客房模式，仅支持点歌）" in prompt
    assert "FM999999" in prompt
    assert "* 称谓: 浩哥" in prompt
    assert "喜欢周杰伦" in prompt


@pytest.mark.asyncio
async def test_port_failure_falls_back_to_no_result():
    port = InMemoryNaturalLanguageResolver(error=TimeoutError("timed out"))
    use_case = _use_case(port)

    assert await use_case.resolve(user_text="放歌", user_name="David") is None
    assert len(port.calls) == 1
