"""
专注人数事件 - 监控 tvStudyRoomDesc（配置 key: focus_count）文案变化。

人数变化时更新 InfoManager.focus_count，并通知 CommandManager 以执行
数据库 focus_events 中的联动命令（:focus add 者各自一条记录，按配置用户入队）。
"""

import re

from ushareiplay.core.base_event import BaseEvent


class FocusCountEvent(BaseEvent):
    """专注人数事件处理器"""

    previous_focus_count = None

    async def handle(self, key: str, element_wrapper):
        """
        解析专注人数；变化时更新 InfoManager、notify_focus_count_change。

        Returns:
            False：不中断同轮其它事件处理。
        """
        try:
            current_focus_count_text = element_wrapper.text
            if not current_focus_count_text:
                return False

            match = re.search(r"(\d+)人专注中", current_focus_count_text)
            if not match:
                return False

            current_focus_count = int(match.group(1))

            if self.previous_focus_count == current_focus_count:
                return False

            before = self.previous_focus_count
            self.previous_focus_count = current_focus_count

            from ushareiplay.managers.info_manager import InfoManager
            from ushareiplay.managers.command_manager import CommandManager

            info_manager = InfoManager.instance()
            info_manager.focus_count = current_focus_count

            await CommandManager.instance().notify_focus_count_change(before, current_focus_count)

            return False

        except Exception as e:
            self.logger.error(f"Error processing focus count event: {str(e)}")
            return False

