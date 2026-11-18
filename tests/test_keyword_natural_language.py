import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ushareiplay.adapters.inbound.runtime.keyword_command_sink import (
    QueueKeywordCommandSink,
)
from ushareiplay.adapters.inbound.runtime.keyword_nl_fallback import (
    NaturalLanguageFallbackAdapter,
)
from ushareiplay.adapters.inbound.runtime.chat_intake import ChatIntakeKind, ChatIntakeResult
from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
from ushareiplay.modules.command.domain import NaturalLanguageResult
from ushareiplay.modules.command.use_cases import KeywordUseCases
from tests.fakes.in_memory_keyword_repository import InMemoryKeywordRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository

_LOGGER = SimpleNamespace(
    info=lambda *_args, **_kwargs: None,
    error=lambda *_args, **_kwargs: None,
    warning=lambda *_args, **_kwargs: None,
)


class _Presence:
    def is_user_online(self, username):
        return True


class _ChatLogs:
    async def record(self, username, content):
        return None


class _NoConfig:
    def load(self):
        return None


def _run(coro):
    return asyncio.run(coro)


def _use_cases(fallback):
    users = InMemoryUserRepository()
    return KeywordUseCases(
        repository=InMemoryKeywordRepository(users),
        users=users,
        presence=_Presence(),
        queue=QueueKeywordCommandSink(MessageQueue.instance()),
        chat_logs=_ChatLogs(),
        config_source=_NoConfig(),
        fallback=fallback,
        logger=_LOGGER,
    )


@pytest.fixture(autouse=True)
def _clear_message_queue():
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    yield
    _run(queue.clear_queue())


@pytest.mark.asyncio
async def test_keyword_takes_precedence_over_natural_language(monkeypatch):
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue

    mock_resolve = AsyncMock()
    fallback = SimpleNamespace(resolve=mock_resolve)
    use_cases = _use_cases(fallback)
    alice = await use_cases._users.get_or_create("Alice")
    await use_cases._repository.create(
        keyword="520",
        command=":play love song",
        creator_id=alice.id,
        is_public=True,
    )

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Alice",
        text="520",
        params="",
    )

    await use_cases.dispatch_mention(intake_result, sleep_exempt=True)

    # Assert keyword was executed, resolver was NOT called
    mock_resolve.assert_not_called()
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == ":play love song"
    assert msg.nickname == "Alice"
    assert msg.sleep_exempt is True


@pytest.mark.asyncio
async def test_unmatched_mention_resolves_to_command(monkeypatch):
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue

    mock_resolve = AsyncMock(
        return_value=NaturalLanguageResult(type="command", content=":play 周杰伦 晴天")
    )
    use_cases = _use_cases(SimpleNamespace(resolve=mock_resolve))

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Bob",
        text="帮我放一首周杰伦的晴天",
        params="",
    )

    await use_cases.dispatch_mention(intake_result, sleep_exempt=True)

    mock_resolve.assert_awaited_once()
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == ":play 周杰伦 晴天"
    assert msg.nickname == "Bob"
    assert msg.sleep_exempt is True


@pytest.mark.asyncio
async def test_unmatched_mention_resolves_to_reply(monkeypatch):
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue

    mock_resolve = AsyncMock(
        return_value=NaturalLanguageResult(type="reply", content="你好呀！我是小助手~")
    )
    use_cases = _use_cases(SimpleNamespace(resolve=mock_resolve))

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Charlie",
        text="你好呀",
        params="",
    )

    await use_cases.dispatch_mention(intake_result, sleep_exempt=True)

    mock_resolve.assert_awaited_once()
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == "你好呀！我是小助手~"
    assert msg.nickname == "Charlie"
    assert msg.sleep_exempt is True


@pytest.mark.asyncio
async def test_unmatched_mention_fallback_on_resolver_failure(monkeypatch):
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue

    # Mock resolver returning None (failure or timeout)
    mock_resolve = AsyncMock(return_value=None)
    use_cases = _use_cases(SimpleNamespace(resolve=mock_resolve))
    use_cases._default_keyword_command = ":help"

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="David",
        text="未知的自然语言",
        params="",
    )

    await use_cases.dispatch_mention(intake_result, sleep_exempt=True)

    mock_resolve.assert_awaited_once()
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == ":help"
    assert msg.nickname == "David"
    assert msg.sleep_exempt is True


@pytest.mark.asyncio
async def test_keyword_manager_resolves_root_config_from_controller(monkeypatch):
    """Verify the keyword fallback reads root config (with llm and commands)."""
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue

    root_config = {
        "soul": {"room_owner": "Chainer"},
        "commands": [{"prefix": "play", "level": 1, "description": "播放歌曲"}],
        "llm": {"enabled": True, "api_key": "test-key"},
    }
    from ushareiplay.adapters.outbound.llm.natural_language_resolver import (
        OpenAICompatibleNaturalLanguageResolver,
    )
    from ushareiplay.modules.command.use_cases import ResolveNaturalLanguage
    from ushareiplay.modules.shared.config import ConfigView

    llm_cfg = dict(ConfigView(root_config).maybe_section("llm").data)
    resolver = ResolveNaturalLanguage(
        OpenAICompatibleNaturalLanguageResolver(llm_cfg), llm_cfg
    )
    fallback = NaturalLanguageFallbackAdapter(
        commands_config=lambda: root_config["commands"],
        catalogue=lambda: None,
        room_info=lambda: None,
        playback_info=lambda: None,
        resolver=resolver,
    )
    use_cases = _use_cases(fallback)

    with patch(
        "ushareiplay.modules.command.use_cases.ResolveNaturalLanguage.resolve",
        new_callable=AsyncMock,
    ) as mock_resolve:
        mock_resolve.return_value = NaturalLanguageResult(
            type="command", content=":play 胡彦斌 潇湘雨"
        )

        intake_result = ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Outlier",
            text="来首胡彦斌的潇湘雨",
            params="",
        )

        await use_cases.dispatch_mention(intake_result, sleep_exempt=True)

        assert resolver.enabled is True
        mock_resolve.assert_awaited_once()
        messages = await MessageQueue.instance().get_all_messages()
        assert len(messages) == 1
        msg = next(iter(messages.values()))
        assert msg.content == ":play 胡彦斌 潇湘雨"


@pytest.mark.asyncio
async def test_keyword_mention_with_room_owner_dispatches_properly(monkeypatch):
    from ushareiplay.adapters.inbound.runtime.chat_intake import classify_chat_line
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue

    mock_resolve = AsyncMock(
        return_value=NaturalLanguageResult(type="command", content=":play 周杰伦 晴天")
    )
    use_cases = _use_cases(SimpleNamespace(resolve=mock_resolve))

    raw_chat = "souler[Alice]说: @Chainer 帮我放一首周杰伦的晴天"
    intake_result = classify_chat_line(raw_chat, room_owner="Chainer")
    assert intake_result.kind == ChatIntakeKind.KEYWORD_MENTION

    await use_cases.dispatch_mention(intake_result, sleep_exempt=True)

    mock_resolve.assert_awaited_once()
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == ":play 周杰伦 晴天"
    assert msg.nickname == "Alice"


def test_get_playback_info_enrichment():
    from ushareiplay.adapters.inbound.runtime.keyword_nl_fallback import (
        PlaybackInfoProvider,
    )
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
    from ushareiplay.modules.playback.use_cases import PlaylistSession

    broadcaster = PlaybackBroadcaster.initialize()
    playlist_session = PlaylistSession()

    broadcaster._playback_info_cache = {
        "song": "Fictional (Stripped)",
        "singer": "Khloe Rose",
        "album": "Fictional (Stripped)",
        "release_date": "2023-05-12",
    }
    playlist_session.player_name = "不约儿童🐏🐏"
    playlist_session.current_playlist_name = "咿鸭咿鸭yo宝天天开心"
    playlist_session.list_mode = "playlist"

    fake_music_handler = SimpleNamespace(
        list_mode="playlist",
        play_mode_key="random",
        play_mode_key_to_name=lambda k: "随机播放" if k == "random" else "未知",
    )

    info = PlaybackInfoProvider(broadcaster, playlist_session, fake_music_handler)()
    assert info is not None
    assert info["song"] == "Fictional (Stripped)"
    assert info["singer"] == "Khloe Rose"
    assert info["album"] == "Fictional (Stripped)"
    assert info["release_date"] == "2023-05-12"
    assert info["player"] == "不约儿童🐏🐏"
    assert info["playlist_name"] == "咿鸭咿鸭yo宝天天开心"
    assert info["playlist_type"] == "歌单"
    assert info["play_mode"] == "随机播放"


def test_get_playback_info_tolerates_missing_playlist_context():
    from ushareiplay.adapters.inbound.runtime.keyword_nl_fallback import (
        PlaybackInfoProvider,
    )
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster

    broadcaster = PlaybackBroadcaster.initialize()
    broadcaster._playback_info_cache = {"song": "SongA", "singer": "SingerA"}

    info = PlaybackInfoProvider(broadcaster, None, None)()
    assert info is not None
    assert info["song"] == "SongA"


@pytest.mark.asyncio
async def test_mention_query_own_playlist_e2e(monkeypatch):
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
    from ushareiplay.modules.playback.use_cases import PlaylistSession

    from ushareiplay.adapters.inbound.runtime.keyword_nl_fallback import (
        PlaybackInfoProvider,
    )
    from ushareiplay.adapters.outbound.llm.natural_language_resolver import (
        OpenAICompatibleNaturalLanguageResolver,
    )
    from ushareiplay.modules.command.use_cases import ResolveNaturalLanguage

    llm_cfg = {
        "enabled": True,
        "api_key": "test-key",
        "base_url": "https://api.openai.com/v1",
    }
    llm_client = OpenAICompatibleNaturalLanguageResolver(llm_cfg)
    fallback = NaturalLanguageFallbackAdapter(
        commands_config=lambda: [{"prefix": "play", "level": 1}],
        catalogue=lambda: None,
        room_info=lambda: None,
        playback_info=lambda: PlaybackInfoProvider(
            broadcaster, playlist_session, fake_music_handler
        )(),
        resolver=ResolveNaturalLanguage(llm_client, llm_cfg),
    )
    use_cases = _use_cases(fallback)

    broadcaster = PlaybackBroadcaster.initialize()
    broadcaster._playback_info_cache = {
        "song": "Fictional (Stripped)",
        "singer": "Khloe Rose",
        "album": "Fictional (Stripped)",
        "release_date": "2023-05-12",
    }
    playlist_session = PlaylistSession()
    playlist_session.player_name = "不约儿童🐏🐏"
    playlist_session.current_playlist_name = "咿鸭咿鸭yo宝天天开心"
    playlist_session.list_mode = "playlist"

    fake_music_handler = SimpleNamespace(
        list_mode="playlist",
        play_mode_key="random",
        play_mode_key_to_name=lambda k: "随机播放" if k == "random" else "未知",
    )
    monkeypatch.setattr(
        "ushareiplay.adapters.outbound.appium.qq_music.qq_music_handler.QQMusicHandler.instance",
        lambda: fake_music_handler,
    )

    captured_payload = {}

    async def _fake_call_api(payload, timeout=None):
        nonlocal captured_payload
        captured_payload = payload
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "type": "reply",
                                "content": "是的，当前正在播放你的歌单《咿鸭咿鸭yo宝天天开心》哦~",
                            }
                        )
                    }
                }
            ]
        }
        return json.dumps(mock_response)

    monkeypatch.setattr(
        llm_client,
        "_call_api",
        _fake_call_api,
    )

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="不约儿童🐏🐏",
        text="现在是播我的歌单吗",
        params="",
    )

    await use_cases.dispatch_mention(intake_result, sleep_exempt=True)

    # Verify system prompt contained complete context
    system_prompt = captured_payload["messages"][0]["content"]
    assert "当前播放者/点歌人: 不约儿童🐏🐏" in system_prompt
    assert "当前播放列表/歌单: [歌单] 咿鸭咿鸭yo宝天天开心 (by 不约儿童🐏🐏)" in system_prompt
    assert "播放模式: 随机播放" in system_prompt

    # Verify message queue has the response
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == "[智能] 是的，当前正在播放你的歌单《咿鸭咿鸭yo宝天天开心》哦~"
    assert msg.nickname == "不约儿童🐏🐏"
    assert msg.sleep_exempt is True


@pytest.mark.asyncio
async def test_mention_query_others_playlist_e2e(monkeypatch):
    from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
    from ushareiplay.modules.playback.use_cases import PlaylistSession

    from ushareiplay.adapters.inbound.runtime.keyword_nl_fallback import (
        PlaybackInfoProvider,
    )
    from ushareiplay.adapters.outbound.llm.natural_language_resolver import (
        OpenAICompatibleNaturalLanguageResolver,
    )
    from ushareiplay.modules.command.use_cases import ResolveNaturalLanguage

    llm_cfg = {
        "enabled": True,
        "api_key": "test-key",
        "base_url": "https://api.openai.com/v1",
    }
    llm_client = OpenAICompatibleNaturalLanguageResolver(llm_cfg)
    fallback = NaturalLanguageFallbackAdapter(
        commands_config=lambda: [{"prefix": "play", "level": 1}],
        catalogue=lambda: None,
        room_info=lambda: None,
        playback_info=lambda: PlaybackInfoProvider(
            broadcaster, playlist_session, fake_music_handler
        )(),
        resolver=ResolveNaturalLanguage(llm_client, llm_cfg),
    )
    use_cases = _use_cases(fallback)

    broadcaster = PlaybackBroadcaster.initialize()
    broadcaster._playback_info_cache = {
        "song": "Fictional (Stripped)",
        "singer": "Khloe Rose",
    }
    playlist_session = PlaylistSession()
    playlist_session.player_name = "不约儿童🐏🐏"
    playlist_session.current_playlist_name = "咿鸭咿鸭yo宝天天开心"
    playlist_session.list_mode = "playlist"

    fake_music_handler = SimpleNamespace(
        list_mode="playlist",
        play_mode_key="random",
        play_mode_key_to_name=lambda k: "随机播放" if k == "random" else "未知",
    )
    monkeypatch.setattr(
        "ushareiplay.adapters.outbound.appium.qq_music.qq_music_handler.QQMusicHandler.instance",
        lambda: fake_music_handler,
    )

    async def _fake_call_api(payload, timeout=None):
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "type": "reply",
                                "content": "现在播放的不是你的歌单哦，当前正在播放 不约儿童🐏🐏 点播的歌单《咿鸭咿鸭yo宝天天开心》~",
                            }
                        )
                    }
                }
            ]
        }
        return json.dumps(mock_response)

    monkeypatch.setattr(
        llm_client,
        "_call_api",
        _fake_call_api,
    )

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Alice",
        text="现在是播我的歌单吗",
        params="",
    )

    await use_cases.dispatch_mention(intake_result, sleep_exempt=True)

    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == "[智能] 现在播放的不是你的歌单哦，当前正在播放 不约儿童🐏🐏 点播的歌单《咿鸭咿鸭yo宝天天开心》~"
    assert msg.nickname == "Alice"
