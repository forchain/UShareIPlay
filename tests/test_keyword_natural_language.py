import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ushareiplay.core.chat_intake import ChatIntakeKind, ChatIntakeResult
from ushareiplay.core.natural_language_resolver import NaturalLanguageResult


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_message_queue():
    from ushareiplay.core.message_queue import MessageQueue

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    yield
    _run(queue.clear_queue())


@pytest.mark.asyncio
async def test_keyword_takes_precedence_over_natural_language(monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.keyword_manager import KeywordManager

    keyword_manager = KeywordManager.initialize()
    keyword_manager._logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
    )
    keyword_manager._config = {
        "llm": {"enabled": True, "api_key": "test"},
        "commands": [{"prefix": "play", "level": 1}],
    }

    # Register an exact keyword
    async def _mock_find_keyword(keyword, username):
        if keyword == "520":
            return SimpleNamespace(keyword="520", command=":play love song", mode="sequence")
        return None

    monkeypatch.setattr(keyword_manager, "find_keyword", _mock_find_keyword)

    # Mock resolver
    mock_resolve = AsyncMock()
    keyword_manager._nl_resolver = SimpleNamespace(resolve=mock_resolve)

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Alice",
        text="520",
        params="",
    )

    await keyword_manager.dispatch_mention(intake_result, sleep_exempt=True)

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
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.keyword_manager import KeywordManager

    keyword_manager = KeywordManager.initialize()
    keyword_manager._logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
    )
    keyword_manager._config = {
        "llm": {"enabled": True, "api_key": "test"},
        "commands": [{"prefix": "play", "level": 1}],
    }

    async def _mock_find_keyword(_keyword, _username):
        return None

    monkeypatch.setattr(keyword_manager, "find_keyword", _mock_find_keyword)

    mock_resolve = AsyncMock(
        return_value=NaturalLanguageResult(type="command", content=":play 周杰伦 晴天")
    )
    keyword_manager._nl_resolver = SimpleNamespace(resolve=mock_resolve)

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Bob",
        text="帮我放一首周杰伦的晴天",
        params="",
    )

    await keyword_manager.dispatch_mention(intake_result, sleep_exempt=True)

    mock_resolve.assert_awaited_once()
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == ":play 周杰伦 晴天"
    assert msg.nickname == "Bob"
    assert msg.sleep_exempt is True


@pytest.mark.asyncio
async def test_unmatched_mention_resolves_to_reply(monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.keyword_manager import KeywordManager

    keyword_manager = KeywordManager.initialize()
    keyword_manager._logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
    )
    keyword_manager._config = {
        "llm": {"enabled": True, "api_key": "test"},
    }

    async def _mock_find_keyword(_keyword, _username):
        return None

    monkeypatch.setattr(keyword_manager, "find_keyword", _mock_find_keyword)

    mock_resolve = AsyncMock(
        return_value=NaturalLanguageResult(type="reply", content="你好呀！我是小助手~")
    )
    keyword_manager._nl_resolver = SimpleNamespace(resolve=mock_resolve)

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Charlie",
        text="你好呀",
        params="",
    )

    await keyword_manager.dispatch_mention(intake_result, sleep_exempt=True)

    mock_resolve.assert_awaited_once()
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == "你好呀！我是小助手~"
    assert msg.nickname == "Charlie"
    assert msg.sleep_exempt is True


@pytest.mark.asyncio
async def test_unmatched_mention_fallback_on_resolver_failure(monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.keyword_manager import KeywordManager

    keyword_manager = KeywordManager.initialize()
    keyword_manager._logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
    )
    keyword_manager._config = {
        "llm": {"enabled": True, "api_key": "test"},
    }
    keyword_manager._default_keyword_command = ":help"

    async def _mock_find_keyword(_keyword, _username):
        return None

    monkeypatch.setattr(keyword_manager, "find_keyword", _mock_find_keyword)

    # Mock resolver returning None (failure or timeout)
    mock_resolve = AsyncMock(return_value=None)
    keyword_manager._nl_resolver = SimpleNamespace(resolve=mock_resolve)

    intake_result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="David",
        text="未知的自然语言",
        params="",
    )

    await keyword_manager.dispatch_mention(intake_result, sleep_exempt=True)

    mock_resolve.assert_awaited_once()
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    msg = next(iter(messages.values()))
    assert msg.content == ":help"
    assert msg.nickname == "David"
    assert msg.sleep_exempt is True


@pytest.mark.asyncio
async def test_keyword_manager_resolves_root_config_from_controller(monkeypatch):
    """Verify KeywordManager reads root config (with llm and commands) instead of only soul config."""
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.keyword_manager import KeywordManager

    keyword_manager = KeywordManager.initialize()
    keyword_manager._logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
    )
    keyword_manager._config = None
    keyword_manager._nl_resolver = None

    root_config = {
        "soul": {"room_owner": "Chainer"},
        "commands": [{"prefix": "play", "level": 1, "description": "播放歌曲"}],
        "llm": {"enabled": True, "api_key": "test-key"},
    }

    # Simulate SoulHandler where handler.config is only root_config["soul"]
    # and handler.controller.config is root_config
    fake_controller = SimpleNamespace(config=root_config)
    fake_handler = SimpleNamespace(config=root_config["soul"], controller=fake_controller)
    keyword_manager._handler = fake_handler

    async def _mock_find_keyword(_keyword, _username):
        return None

    monkeypatch.setattr(keyword_manager, "find_keyword", _mock_find_keyword)

    with patch("ushareiplay.core.natural_language_resolver.NaturalLanguageResolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = NaturalLanguageResult(type="command", content=":play 胡彦斌 潇湘雨")

        intake_result = ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Outlier",
            text="来首胡彦斌的潇湘雨",
            params="",
        )

        await keyword_manager.dispatch_mention(intake_result, sleep_exempt=True)

        assert keyword_manager.nl_resolver.enabled is True
        mock_resolve.assert_awaited_once()
        messages = await MessageQueue.instance().get_all_messages()
        assert len(messages) == 1
        msg = next(iter(messages.values()))
        assert msg.content == ":play 胡彦斌 潇湘雨"

