"""
专注数事件 - 监控专注人数变化

当检测到专注数变化时，自动为群主找座位。
"""

import re

from ..core.base_event import BaseEvent


class FocusCountEvent(BaseEvent):
    """专注数事件处理器"""

    # 类变量，维护上一次的专注数
    previous_focus_count = None

    def handle(self, key: str, element_wrapper):
        """
        处理专注数事件
        
        检查专注数是否变化，如果变化则调用 find_owner_seat()
        
        Args:
            key: 触发事件的元素 key，这里是 'focus_count'
            element_wrapper: ElementWrapper 实例，包装了专注数元素
            
        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        try:
            # 获取元素文本
            current_focus_count_text = element_wrapper.text
            if not current_focus_count_text:
                return False

            # 使用正则表达式提取专注数
            match = re.search(r'(\d+)人专注中', current_focus_count_text)
            if not match:
                return False

            current_focus_count = int(match.group(1))

            # 如果专注数没有变化，直接返回
            if self.previous_focus_count == current_focus_count:
                return False

            # 专注数变化，更新并调用 find_owner_seat
            self.previous_focus_count = current_focus_count

            # 通过 controller 获取 seat_manager 并调用 find_owner_seat
            result = self.controller.seat_manager.seating.find_owner_seat()
            if 'success' in result:
                self.logger.info(f"Focus count changed to: {current_focus_count}, owner seat found")
            else:
                self.logger.debug(f"Focus count changed to: {current_focus_count}, find_owner_seat result: {result}")

            return True

        except Exception as e:
            self.logger.error(f"Error processing focus count event: {str(e)}")
            return False

