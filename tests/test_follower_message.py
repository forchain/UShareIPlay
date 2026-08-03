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
