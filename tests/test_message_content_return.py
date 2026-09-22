import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ushareiplay.events.message_content import MessageContentEvent


class _FakeWrapper:
    def __init__(self, text: str):
        self.content = text


@pytest.mark.asyncio
async def test_message_content_event_triggers_return_when_should_trigger():
    handler_mock = MagicMock()
    handler_mock.logger = MagicMock()
    handler_mock.config = {}
    event = MessageContentEvent(handler_mock)

    mock_msg_manager = MagicMock()
    mock_msg_manager.latest_chats = ["不约儿童🐏🐏坐着魔毯来啦"]
    mock_msg_manager.recent_chats = []

    mock_chat_logger = MagicMock()
    with (
        patch("ushareiplay.managers.message_manager.MessageManager.instance", return_value=mock_msg_manager),
        patch("ushareiplay.managers.message_manager.get_chat_logger", return_value=mock_chat_logger),
        patch("ushareiplay.state.presence_tracker.PresenceTracker.instance") as mock_presence,
        patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd,
    ):
        mock_presence.return_value.should_trigger_return.return_value = True
        mock_presence.return_value.record_return = MagicMock()
        mock_cmd.return_value.notify_user_return = AsyncMock()

        await event.handle("message_content", [_FakeWrapper("不约儿童🐏🐏坐着魔毯来啦")])

        mock_presence.return_value.should_trigger_return.assert_called_once_with("不约儿童🐏🐏")
        mock_presence.return_value.record_return.assert_called_once_with("不约儿童🐏🐏")
        mock_cmd.return_value.notify_user_return.assert_called_once_with("不约儿童🐏🐏")
        mock_chat_logger.critical.assert_called_once_with("不约儿童🐏🐏坐着魔毯来啦")
        mock_chat_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_message_content_event_skips_return_when_not_eligible():
    handler_mock = MagicMock()
    handler_mock.logger = MagicMock()
    handler_mock.config = {}
    event = MessageContentEvent(handler_mock)

    mock_msg_manager = MagicMock()
    mock_msg_manager.latest_chats = ["[Joyer]的兄弟[Outlier]进来了."]
    mock_msg_manager.recent_chats = []

    mock_chat_logger = MagicMock()
    with (
        patch("ushareiplay.managers.message_manager.MessageManager.instance", return_value=mock_msg_manager),
        patch("ushareiplay.managers.message_manager.get_chat_logger", return_value=mock_chat_logger),
        patch("ushareiplay.state.presence_tracker.PresenceTracker.instance") as mock_presence,
        patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd,
    ):
        # User not online or recently entered -> should_trigger_return is False
        mock_presence.return_value.should_trigger_return.return_value = False
        mock_presence.return_value.record_return = MagicMock()
        mock_cmd.return_value.notify_user_return = AsyncMock()

        await event.handle("message_content", [_FakeWrapper("[Joyer]的兄弟[Outlier]进来了.")])

        mock_presence.return_value.should_trigger_return.assert_called_once_with("Outlier")
        mock_presence.return_value.record_return.assert_not_called()
        mock_cmd.return_value.notify_user_return.assert_not_called()
        mock_chat_logger.critical.assert_not_called()
        mock_chat_logger.info.assert_called_once_with("[Joyer]的兄弟[Outlier]进来了.")
