import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ushareiplay.events.message_content import MessageContentEvent


class _FakeWrapper:
    def __init__(self, text: str):
        self.content = text


def _event(handler):
    return MessageContentEvent(handler)


@pytest.mark.asyncio
async def test_message_content_event_triggers_return_when_should_trigger(chat_window):
    """入场横幅经 MessageManager.dispatch 触发「用户返回」。"""
    event = _event(chat_window.handler)

    with (
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
        chat_window.logger.critical.assert_called_once_with("不约儿童🐏🐏坐着魔毯来啦")
        chat_window.logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_message_content_event_skips_return_when_not_eligible(chat_window):
    event = _event(chat_window.handler)

    with (
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
        chat_window.logger.info.assert_called_once_with("[Joyer]的兄弟[Outlier]进来了.")
