"""
FollowerMessageEvent 消息解析与事件处理测试
"""

import pytest
from ushareiplay.events.follower_message import FollowerMessageEvent


class TestFollowerMessageParser:
    """测试 FollowerMessageEvent 的消息文本解析功能"""

    def setup_method(self):
        from unittest.mock import MagicMock
        mock_handler = MagicMock()
        mock_handler.logger = MagicMock()
        self.event = FollowerMessageEvent(handler=mock_handler)

    @pytest.mark.parametrize(
        "message_text, expected_nickname, expected_is_join",
        [
            # 基础进入房间消息
            ("你关注的Outlier进入房间啦，打个招呼吧～", "Outlier", True),
            ("你的兄弟 Outlier进来啦～", "Outlier", True),
            # 用户日志中出现的 Warning 消息格式
            ("你的兄弟 Outlier正在房间玩～", "Outlier", True),
            ("你的密友Chainer正在房间里，打个招呼吧～", "Chainer", True),
            # 扩展场景：带空格/无空格、各种关系与动作
            ("你的死党 张三 正在房间里，打个招呼吧～", "张三", True),
            ("你的特别关注李四 正在房间里", "李四", True),
            ("你的好友 王五 进来啦～", "王五", True),
            ("你的挚友小红进入房间啦", "小红", True),
            ("你的神秘嘉宾 Alex 来到了房间", "Alex", True),
            # 点赞消息
            ("荒草 为派对点赞了", "荒草", False),
            # 无法解析的非法格式
            ("系统公告：欢迎使用派对功能", None, False),
            ("", None, False),
        ],
    )
    def test_parse_message(self, message_text, expected_nickname, expected_is_join):
        nickname, is_join = self.event._parse_message(message_text)
        assert nickname == expected_nickname
        assert is_join == expected_is_join


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

