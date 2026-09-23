"""Quoted Message propagation through logging, deduplication and context (#314)."""

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.events.message_content import MessageContentEvent


class _FakeWrapper:
    """Stands in for an ElementWrapper that already carries a composed message."""

    def __init__(self, text: str):
        self.content = text


def _event(room_owner: str = "群主"):
    handler = MagicMock()
    handler.logger = MagicMock()
    handler.config = {"soul": {"room_owner": room_owner}}
    return MessageContentEvent(handler)


@pytest.mark.asyncio
async def test_quoted_message_is_logged_and_kept_for_deduplication():
    message_manager = MagicMock()
    message_manager.latest_chats = deque(maxlen=3)
    message_manager.recent_chats = deque(maxlen=3)
    message_manager.process_new_messages = AsyncMock()
    message_manager.process_missed_messages = AsyncMock()
    chat_logger = MagicMock()

    event = _event()
    first = "souler[Bob]说：「Alice：今天天气不错」 哈哈"
    second = "souler[Bob]说：「Dave：晚安」 哈哈"

    with (
        patch(
            "ushareiplay.managers.message_manager.MessageManager.instance",
            return_value=message_manager,
        ),
        patch(
            "ushareiplay.managers.message_manager.get_chat_logger",
            return_value=chat_logger,
        ),
        patch("ushareiplay.managers.command_manager.CommandManager.instance"),
    ):
        await event.handle("message_content", [_FakeWrapper(first)])
        await event.handle("message_content", [_FakeWrapper(first), _FakeWrapper(second)])

    # Same utterance, different quote → the second must not be dropped as a duplicate.
    assert list(message_manager.recent_chats) == [first, second]
    assert [call.args[0] for call in chat_logger.info.call_args_list] == [first, second]


@pytest.mark.asyncio
async def test_command_inside_a_quote_does_not_trigger_command_processing():
    message_manager = MagicMock()
    message_manager.latest_chats = deque(maxlen=3)
    message_manager.recent_chats = deque(maxlen=3)
    message_manager.process_new_messages = AsyncMock()
    message_manager.process_missed_messages = AsyncMock()
    chat_logger = MagicMock()

    event = _event()
    with (
        patch(
            "ushareiplay.managers.message_manager.MessageManager.instance",
            return_value=message_manager,
        ),
        patch(
            "ushareiplay.managers.message_manager.get_chat_logger",
            return_value=chat_logger,
        ),
        patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd,
    ):
        await event.handle(
            "message_content",
            [_FakeWrapper("souler[Bob]说：「Alice：:play 晴天」 哈哈哈")],
        )

    mock_cmd.return_value.notify_user_return.assert_not_called()
    message_manager.process_new_messages.assert_not_called()
    assert [call.args[0] for call in chat_logger.info.call_args_list] == [
        "souler[Bob]说：「Alice：:play 晴天」 哈哈哈"
    ]


@pytest.mark.asyncio
async def test_sender_command_after_a_quote_reaches_command_processing():
    message_manager = MagicMock()
    message_manager.latest_chats = deque(maxlen=3)
    message_manager.recent_chats = deque(maxlen=3)
    message_manager.process_new_messages = AsyncMock()
    message_manager.process_missed_messages = AsyncMock()
    chat_logger = MagicMock()

    event = _event()
    composed = "souler[Bob]说：「Alice：哈哈」 :play 晴天"
    with (
        patch(
            "ushareiplay.managers.message_manager.MessageManager.instance",
            return_value=message_manager,
        ),
        patch(
            "ushareiplay.managers.message_manager.get_chat_logger",
            return_value=chat_logger,
        ),
        patch("ushareiplay.managers.command_manager.CommandManager.instance"),
    ):
        await event.handle("message_content", [_FakeWrapper(composed)])

    message_manager.process_new_messages.assert_awaited_once()
    assert [call.args[0] for call in chat_logger.critical.call_args_list] == [composed]


@pytest.mark.asyncio
async def test_mention_inside_a_quote_is_not_dispatched():
    message_manager = MagicMock()
    message_manager.latest_chats = deque(maxlen=3)
    message_manager.recent_chats = deque(maxlen=3)
    message_manager.process_new_messages = AsyncMock()
    message_manager.process_missed_messages = AsyncMock()
    chat_logger = MagicMock()

    event = _event()
    with (
        patch(
            "ushareiplay.managers.message_manager.MessageManager.instance",
            return_value=message_manager,
        ),
        patch(
            "ushareiplay.managers.message_manager.get_chat_logger",
            return_value=chat_logger,
        ),
        patch("ushareiplay.managers.keyword_manager.KeywordManager.instance") as mock_keyword,
    ):
        mock_keyword.return_value.dispatch_mention = AsyncMock()
        await event.handle(
            "message_content",
            [_FakeWrapper("souler[Bob]说：「Alice：@群主 点歌」 哈哈哈")],
        )

    mock_keyword.return_value.dispatch_mention.assert_not_called()
    assert [call.args[0] for call in chat_logger.info.call_args_list] == [
        "souler[Bob]说：「Alice：@群主 点歌」 哈哈哈"
    ]


@pytest.mark.asyncio
async def test_sender_mention_after_a_quote_is_dispatched_with_its_quote():
    message_manager = MagicMock()
    message_manager.latest_chats = deque(maxlen=3)
    message_manager.recent_chats = deque(maxlen=3)
    message_manager.process_new_messages = AsyncMock()
    message_manager.process_missed_messages = AsyncMock()
    chat_logger = MagicMock()

    event = _event()
    composed = "souler[Bob]说：「Alice：哈哈」 @群主 点歌 晴天"
    with (
        patch(
            "ushareiplay.managers.message_manager.MessageManager.instance",
            return_value=message_manager,
        ),
        patch(
            "ushareiplay.managers.message_manager.get_chat_logger",
            return_value=chat_logger,
        ),
        patch("ushareiplay.managers.keyword_manager.KeywordManager.instance") as mock_keyword,
    ):
        mock_keyword.return_value.dispatch_mention = AsyncMock()
        await event.handle("message_content", [_FakeWrapper(composed)])

    result = mock_keyword.return_value.dispatch_mention.await_args.args[0]
    assert result.text == "点歌"
    assert result.params == "晴天"
    assert result.quoted_text == "Alice：哈哈"
    assert result.utterance == "「Alice：哈哈」 点歌 晴天"


@pytest.mark.asyncio
async def test_missed_message_scan_anchors_on_the_quote_free_line(monkeypatch):
    from ushareiplay.managers.message_manager import MessageManager

    manager = object.__new__(MessageManager)
    manager.recent_chats = ["souler[Bob]说：「Alice：今天天气不错」 哈哈"]
    manager.latest_chats = []
    manager._chat_logger = MagicMock()

    handler_mock = MagicMock()
    handler_mock.config = {"soul": {"room_owner": "Joyer"}}
    handler_mock.key_actions.switch_to_app.return_value = True
    handler_mock.gesture_handler.scroll_container_until_element.return_value = (
        "message_list",
        MagicMock(),
        ["souler[Bob]说：哈哈", "souler[Carol]说：新消息"],
    )
    handler_mock.element_finder.try_find_element.return_value = None
    manager._handler = handler_mock
    monkeypatch.setattr(manager, "_get_seat_manager", lambda: None)

    await manager.process_missed_messages()

    # The UI renders only the sender's own text for a reply bubble, so the
    # scroll anchor has to be the quote-free line.
    assert (
        handler_mock.gesture_handler.scroll_container_until_element.call_args.args[-1]
        == "souler[Bob]说：哈哈"
    )
    # ... which also keeps the anchor row itself out of the "missed" report.
    assert [call.args[0] for call in manager._chat_logger.warning.call_args_list] == [
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
    from ushareiplay.core.chat_intake import classify_chat_line
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO
    from ushareiplay.managers.keyword_manager import KeywordManager

    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    keyword_manager = KeywordManager.initialize()
    keyword_manager._logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
    )
    keyword_manager._config = {"llm": {"enabled": True}}

    async def _no_keyword(keyword, username):
        return None

    monkeypatch.setattr(keyword_manager, "find_keyword", _no_keyword)
    mock_resolve = AsyncMock(return_value=None)
    keyword_manager._nl_resolver = SimpleNamespace(resolve=mock_resolve)

    result = classify_chat_line(
        "souler[Bob]说：「Alice：哈哈」 @群主 点歌 晴天", room_owner="群主"
    )
    await keyword_manager.dispatch_mention(result, sleep_exempt=True)

    from ushareiplay.dal.user_dao import UserDAO

    user = await UserDAO.get_by_username("Bob")
    logs = await UserChatLogDAO.get_unconsolidated_logs(user.id)
    assert [log.content for log in logs] == ["「Alice：哈哈」 点歌 晴天"]

    assert mock_resolve.await_args.kwargs["user_text"] == "「Alice：哈哈」 点歌 晴天"
