import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.events.message_content import MessageContentEvent
from ushareiplay.core.chat_intake import ChatIntakeKind, classify_chat_line


@pytest_asyncio.fixture
async def db_init():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield
    await manager.close()


@pytest.mark.asyncio
async def test_message_content_event_gift_handling(db_init, monkeypatch):
    handler_mock = MagicMock()
    handler_mock.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(handler_mock)


    # Mock MessageManager and chat_logger
    mock_msg_manager = MagicMock()
    mock_msg_manager.latest_chats = ["souler[🍻🥂🥃🍸🍷🍺]送给Joyer"]
    mock_msg_manager.recent_chats = []

    monkeypatch.setattr("ushareiplay.managers.message_manager.MessageManager.instance", lambda: mock_msg_manager)
    monkeypatch.setattr("ushareiplay.managers.message_manager.get_chat_logger", lambda cfg: MagicMock())

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = MagicMock()
    wrapper.content = "souler[🍻🥂🥃🍸🍷🍺]送给Joyer"

    await event_handler.handle("message_content", wrapper)

    # Verify notify_gift_receive was called with the giver's nickname
    notify_mock.assert_called_once_with("🍻🥂🥃🍸🍷🍺")
