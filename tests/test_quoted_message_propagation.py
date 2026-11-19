"""Quoted Message propagation through logging, deduplication and context (#314)."""

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.inbound.ui_events.message_content import MessageContentEvent


class _FakeWrapper:
    """Stands in for an ElementWrapper that already carries a composed message."""

    def __init__(self, text: str):
        self.content = text


def _event(chat_window):
    return MessageContentEvent(chat_window.handler)


@pytest.mark.asyncio
async def test_quoted_message_is_logged_and_kept_for_deduplication(chat_window):
    event = _event(chat_window)
    chat_window.manager.focus_app_for_queued_commands = AsyncMock()
    chat_window.manager.process_missed_messages = AsyncMock()
    first = "souler[Bob]说：「Alice：今天天气不错」 哈哈"
    second = "souler[Bob]说：「Dave：晚安」 哈哈"

    await event.handle("message_content", [_FakeWrapper(first)])
    await event.handle("message_content", [_FakeWrapper(first), _FakeWrapper(second)])

    # Same utterance, different quote → the second must not be dropped as a duplicate.
    # 再观察一次这两行：两条都已在窗口里，因此没有新行。
    assert chat_window.manager.observe([first, second]).new_lines == ()
    assert [call.args[0] for call in chat_window.logger.info.call_args_list] == [first, second]


@pytest.mark.asyncio
async def test_command_inside_a_quote_does_not_trigger_command_processing(chat_window, monkeypatch):
    event = _event(chat_window)
    chat_window.manager.focus_app_for_queued_commands = AsyncMock()
    chat_window.manager.process_missed_messages = AsyncMock()
    notify_return = AsyncMock()
    monkeypatch.setattr(chat_window.command_manager, "notify_user_return", notify_return)
    await event.handle(
        "message_content",
        [_FakeWrapper("souler[Bob]说：「Alice：:play 晴天」 哈哈哈")],
    )

    notify_return.assert_not_called()
    chat_window.manager.focus_app_for_queued_commands.assert_not_called()
    assert [call.args[0] for call in chat_window.logger.info.call_args_list] == [
        "souler[Bob]说：「Alice：:play 晴天」 哈哈哈"
    ]


@pytest.mark.asyncio
async def test_sender_command_after_a_quote_reaches_command_processing(chat_window):
    event = _event(chat_window)
    chat_window.manager.focus_app_for_queued_commands = AsyncMock()
    chat_window.manager.process_missed_messages = AsyncMock()
    composed = "souler[Bob]说：「Alice：哈哈」 :play 晴天"
    await event.handle("message_content", [_FakeWrapper(composed)])

    chat_window.manager.focus_app_for_queued_commands.assert_awaited_once()
    assert [call.args[0] for call in chat_window.logger.critical.call_args_list] == [composed]


@pytest.mark.asyncio
async def test_mention_inside_a_quote_is_not_dispatched(chat_window):
    event = _event(chat_window)
    chat_window.manager.focus_app_for_queued_commands = AsyncMock()
    chat_window.manager.process_missed_messages = AsyncMock()
    await event.handle(
        "message_content",
        [_FakeWrapper("souler[Bob]说：「Alice：@群主 点歌」 哈哈哈")],
    )
    assert [call.args[0] for call in chat_window.logger.info.call_args_list] == [
        "souler[Bob]说：「Alice：@群主 点歌」 哈哈哈"
    ]


@pytest.mark.asyncio
async def test_sender_mention_after_a_quote_is_dispatched_with_its_quote(chat_window):
    event = _event(chat_window)
    chat_window.manager.focus_app_for_queued_commands = AsyncMock()
    chat_window.manager.process_missed_messages = AsyncMock()
    composed = "souler[Bob]说：「Alice：哈哈」 @群主 点歌 晴天"
    mock_keyword = SimpleNamespace(dispatch_mention=AsyncMock())
    chat_window.manager.configure_keywords(mock_keyword)
    await event.handle("message_content", [_FakeWrapper(composed)])

    result = mock_keyword.dispatch_mention.await_args.args[0]
    assert result.text == "点歌"
    assert result.params == "晴天"
    assert result.quoted_text == "Alice：哈哈"
    assert result.utterance == "「Alice：哈哈」 点歌 晴天"


@pytest.mark.asyncio
async def test_missed_message_scan_anchors_on_the_quote_free_line(chat_window, monkeypatch):
    manager = chat_window.manager
    handler = chat_window.handler
    handler.config = {"soul": {"room_owner": "Joyer"}}
    handler.key_actions = MagicMock()
    handler.key_actions.switch_to_app.return_value = True
    handler.gesture_handler = MagicMock()
    handler.gesture_handler.scroll_container_until_element.return_value = (
        "message_list",
        MagicMock(),
        ["souler[Bob]说：哈哈", "souler[Carol]说：新消息"],
    )
    handler.send_message = MagicMock()
    monkeypatch.setattr(manager, "_get_seat_manager", lambda: None)

    # 通过接口播种窗口：上一轮看到的是带引用的完整行
    manager.observe(["souler[Bob]说：「Alice：今天天气不错」 哈哈"])

    await manager.process_missed_messages()

    # The UI renders only the sender's own text for a reply bubble, so the
    # scroll anchor has to be the quote-free line.
    assert (
        handler.gesture_handler.scroll_container_until_element.call_args.args[-1]
        == "souler[Bob]说：哈哈"
    )
    # ... which also keeps the anchor row itself out of the "missed" report.
    assert [call.args[0] for call in chat_window.logger.warning.call_args_list] == [
        "souler[Carol]说：新消息"
    ]


@pytest_asyncio.fixture
async def db_init():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield
    await manager.close()


@pytest.mark.asyncio
async def test_mention_with_quote_records_the_quote_in_the_user_chat_log(db_init, monkeypatch):
    from ushareiplay.adapters.inbound.runtime.user_memory_chat_log import (
        UserMemoryChatLogRecorder,
    )
    from ushareiplay.adapters.outbound.persistence.chat_log_repository import (
        TortoiseChatLogRepository,
    )
    from ushareiplay.adapters.outbound.persistence.user_memory_repository import (
        TortoiseUserMemoryRepository,
    )
    from ushareiplay.adapters.outbound.persistence.user_repository import (
        TortoiseUserRepository,
    )
    from ushareiplay.adapters.inbound.runtime.chat_intake import classify_chat_line
    from ushareiplay.modules.command.use_cases import KeywordUseCases
    from ushareiplay.modules.user.domain import MemorySettings
    from ushareiplay.modules.user.use_cases import UserMemoryService
    from tests.fakes.in_memory_keyword_repository import InMemoryKeywordRepository
    from tests.fakes.in_memory_memory_distiller import InMemoryMemoryDistiller

    users = TortoiseUserRepository()
    chat_logs = TortoiseChatLogRepository()
    memory = UserMemoryService(
        users=users,
        memories=TortoiseUserMemoryRepository(),
        chat_logs=chat_logs,
        distiller=InMemoryMemoryDistiller(),
        settings=MemorySettings(),
    )
    mock_resolve = AsyncMock(return_value=None)
    keyword_manager = KeywordUseCases(
        repository=InMemoryKeywordRepository(users),
        users=users,
        presence=SimpleNamespace(is_user_online=lambda _name: True),
        queue=SimpleNamespace(enqueue=AsyncMock()),
        chat_logs=UserMemoryChatLogRecorder(memory),
        config_source=SimpleNamespace(load=lambda: None),
        fallback=SimpleNamespace(resolve=mock_resolve),
        logger=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
        ),
    )

    result = classify_chat_line(
        "souler[Bob]说：「Alice：哈哈」 @群主 点歌 晴天", room_owner="群主"
    )
    await keyword_manager.dispatch_mention(result, sleep_exempt=True)

    user = await TortoiseUserRepository().get_by_username("Bob")
    logs = await chat_logs.unconsolidated_logs(user.id)
    assert [log.content for log in logs] == ["「Alice：哈哈」 点歌 晴天"]

    assert mock_resolve.await_args.kwargs["user_text"] == "「Alice：哈哈」 点歌 晴天"


@pytest.mark.asyncio
async def test_quoted_message_losing_its_quote_on_scroll_is_not_redispatched(chat_window):
    event = _event(chat_window)
    chat_window.manager.focus_app_for_queued_commands = AsyncMock()
    chat_window.manager.process_missed_messages = AsyncMock()
    mock_keyword = SimpleNamespace(dispatch_mention=AsyncMock())
    chat_window.manager.configure_keywords(mock_keyword)

    quoted = "souler[Bob]说：「Joyer：[智能] 好，有需要随时告诉我。」 @群主 好嘞"
    quote_free = "souler[Bob]说：@群主 好嘞"
    bot_reply = "souler[群主]说：[智能] 好的，随时都可以告诉我。"

    await event.handle("message_content", [_FakeWrapper(quoted)])
    await event.handle("message_content", [_FakeWrapper(quote_free), _FakeWrapper(bot_reply)])

    assert mock_keyword.dispatch_mention.await_count == 1
    chat_window.manager.process_missed_messages.assert_not_awaited()


def test_observe_anchor_fallback_matches_quote_stripped_anchor(chat_window):
    manager = chat_window.manager
    quoted = "souler[Bob]说：「Alice：早上好」 @群主 你好"
    quote_free = "souler[Bob]说：@群主 你好"
    bot_reply = "souler[群主]说：[智能] 你好呀"

    manager.observe(["p1", "p2", quoted])
    delta = manager.observe(["x1", "x2", "x3", quote_free, bot_reply])

    assert delta.new_lines == (bot_reply,)
    assert delta.missed is False


def test_observe_keeps_distinct_quoted_messages_separate_when_scrolled(chat_window):
    manager = chat_window.manager
    first = "souler[Bob]说：「Alice：今天天气不错」 哈哈"
    second = "souler[Bob]说：「Dave：晚安」 哈哈"

    manager.observe([first])
    delta = manager.observe([second])

    assert delta.new_lines == (second,)
    assert delta.missed is True

