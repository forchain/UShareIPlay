"""
在线人数事件 - 监控在线人数变化

当检测到在线人数变化时，更新 InfoManager 中的在线人数。
"""

import re

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.state.room_state import RoomState
from ushareiplay.state.online_list_scraper import OnlineListScraper


class UserCountEvent(BaseEvent):
    """在线人数事件处理器"""

    def __init__(self, handler, runtime=None):
        super().__init__(handler, runtime)
        self._consecutive_refresh_failures = 0

    async def handle(self, key: str, element_wrapper):
        """
        处理在线人数事件

        解析人数文本并更新到 RoomState；人数变化时触发在线用户列表 UI 刷新。

        Args:
            key: 触发事件的元素 key，这里是 'user_count'
            element_wrapper: ElementWrapper 实例，包装了在线人数元素

        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        try:
            # 获取元素文本
            user_count_text = element_wrapper.text
            if not user_count_text:
                return False

            # 使用正则提取第一个数字序列，例如 "6人", "6人在线", "在线 10 人" -> 6, 6, 10
            match = re.search(r'(\d+)', user_count_text)
            if not match:
                self.logger.warning(f"无法解析人数文本: {user_count_text}")
                return False

            try:
                user_count = int(match.group(1))
            except ValueError:
                # 理论上正则匹配到 \d+ 应该不会转换失败，但为了严谨增加异常处理
                self.logger.warning(f"无法将提取的文本转换为整数: {match.group(1)}")
                return False

            # 更新 RoomState 中的在线人数
            room_state = RoomState.instance()
            if user_count == room_state.user_count:
                return False

            if self.is_ui_busy():
                self.logger.debug(
                    f"UI is busy, deferring online users refresh for user_count={user_count}"
                )
                return False

            success = await OnlineListScraper.instance().refresh_online_users(target_count=user_count)
            if success:
                self._consecutive_refresh_failures = 0
                room_state.user_count = user_count
            else:
                self._consecutive_refresh_failures += 1
                if self._consecutive_refresh_failures >= 10:
                    self.logger.warning(
                        f"Online users refresh failed {self._consecutive_refresh_failures} times, "
                        f"falling back to updating room_state.user_count={user_count}"
                    )
                    room_state.user_count = user_count
                    self._consecutive_refresh_failures = 0
                else:
                    self.logger.debug(
                        f"Online users refresh failed ({self._consecutive_refresh_failures}/10), "
                        f"will retry on next tick"
                    )

            return False

        except Exception as e:
            self.logger.error(f"Error processing user count event: {str(e)}")
            return False
