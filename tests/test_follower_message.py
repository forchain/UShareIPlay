"""
FollowerMessageEvent 事件处理测试

横幅文案的解析表已迁到 tests/test_chat_intake.py —— 横幅文法归 Chat Intake 所有，
这里只覆盖事件独有的 UI 动作与 return 触发。
"""

import pytest
from ushareiplay.events.follower_message import FollowerMessageEvent


class TestFollowerMessageHandler:
    """测试 FollowerMessageEvent.handle 的事件处理与 return 触发"""

    @pytest.mark.asyncio
    async def test_handle_triggers_return_when_should_trigger_return_is_true(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_handler = MagicMock()
        mock_handler.logger = MagicMock()
        mock_handler.config = {}

        mock_greet = MagicMock()
        mock_send = MagicMock()
        mock_handler.element_finder.try_find_element.return_value = mock_greet
        mock_handler.element_finder.wait_for_element_clickable.return_value = mock_send

        event = FollowerMessageEvent(handler=mock_handler)
        # Reset last message
        FollowerMessageEvent.last_follower_message = None

        element_wrapper = MagicMock()
        element_wrapper.text = "你关注的Chainer进入房间啦，打个招呼吧～"

        with (
            patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new=AsyncMock()),
            patch("ushareiplay.managers.message_manager.get_chat_logger") as mock_get_chat_logger,
            patch("ushareiplay.state.presence_tracker.PresenceTracker.instance") as mock_presence,
            patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd,
        ):
            mock_get_chat_logger.return_value = MagicMock()
            mock_presence.return_value.should_trigger_return.return_value = True
            mock_presence.return_value.record_return = MagicMock()
            mock_cmd.return_value.notify_user_return = AsyncMock()

            result = await event.handle("follower_message", element_wrapper)

            assert result is True
            mock_presence.return_value.should_trigger_return.assert_called_once_with("Chainer")
            mock_presence.return_value.record_return.assert_called_once_with("Chainer")
            mock_cmd.return_value.notify_user_return.assert_called_once_with("Chainer")
            mock_greet.click.assert_called_once()
            mock_send.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_skips_return_when_should_trigger_return_is_false(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_handler = MagicMock()
        mock_handler.logger = MagicMock()
        mock_handler.config = {}

        mock_greet = MagicMock()
        mock_send = MagicMock()
        mock_handler.element_finder.try_find_element.return_value = mock_greet
        mock_handler.element_finder.wait_for_element_clickable.return_value = mock_send

        event = FollowerMessageEvent(handler=mock_handler)
        FollowerMessageEvent.last_follower_message = None

        element_wrapper = MagicMock()
        element_wrapper.text = "你的兄弟 Outlier进来啦～"

        with (
            patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new=AsyncMock()),
            patch("ushareiplay.managers.message_manager.get_chat_logger") as mock_get_chat_logger,
            patch("ushareiplay.state.presence_tracker.PresenceTracker.instance") as mock_presence,
            patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd,
        ):
            mock_get_chat_logger.return_value = MagicMock()
            # Simulate: user is newly entering or was recently entered
            mock_presence.return_value.should_trigger_return.return_value = False
            mock_presence.return_value.record_return = MagicMock()
            mock_cmd.return_value.notify_user_return = AsyncMock()

            result = await event.handle("follower_message", element_wrapper)

            assert result is True
            mock_presence.return_value.should_trigger_return.assert_called_once_with("Outlier")
            mock_presence.return_value.record_return.assert_not_called()
            mock_cmd.return_value.notify_user_return.assert_not_called()
            # Greeting still happens
            mock_greet.click.assert_called_once()
            mock_send.click.assert_called_once()

