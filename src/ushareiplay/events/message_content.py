"""
消息内容事件 - 监控消息内容并处理新消息

当检测到 message_content 元素时，从 page_source 中获取所有消息内容，
记录新消息到日志，并处理命令消息。
"""

__multiple__ = True

import traceback

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.core.element_wrapper import composed_message_text
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster


class MessageContentEvent(BaseEvent):
    """消息内容事件处理器"""

    async def handle(self, key: str, element_wrapper):
        """
        处理消息内容事件

        处理消息内容元素列表：
        1. 遍历所有消息，记录新消息到日志
        2. 检查用户进入消息
        3. 如果满足命令格式，调用 get_latest_messages 获取命令

        Args:
            key: 触发事件的元素 key，这里是 'message_content'
            element_wrapper: ElementWrapper 实例或 ElementWrapper 列表（当 __multiple__ = True 时）

        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        try:
            # 判断 element_wrapper 是否是列表（当 __multiple__ = True 时）
            if isinstance(element_wrapper, list):
                # 是 ElementWrapper 列表
                wrapper_list = element_wrapper
            else:
                # 单个 ElementWrapper，转换为列表
                wrapper_list = [element_wrapper]

            if not wrapper_list:
                return False
            content_list = []
            for wrapper in wrapper_list:
                if content := composed_message_text(wrapper):
                    content_list.append(content)

            # 窗口状态与 diff 归 MessageManager：这里只提供本次屏幕上的行，
            # 拿回一个增量（哪些是新行、要不要补漏、补漏的锚点是谁）。
            from ushareiplay.managers.message_manager import MessageManager

            message_manager = MessageManager.instance()
            room_owner = await message_manager.resolve_room_owner()
            delta = message_manager.observe(content_list)

            commands = await message_manager.dispatch(delta.new_lines, room_owner=room_owner)
            has_command_message = bool(commands)

            # 如果有命令消息，交给 CommandManager 执行；否则只做常规更新
            if has_command_message:
                await message_manager.process_new_messages(delta.new_lines)
            else:
                await self._process_update_logic()

            if delta.missed:
                await message_manager.process_missed_messages(delta.anchor)

            return False

        except Exception:
            self.logger.error(f"Error processing message content event: {traceback.format_exc()}")
            return False

    async def _process_update_logic(self):
        """处理更新逻辑（、播放信息等）- 在没有命令消息时执行"""
        try:
            # Update all commands
            command_manager = CommandManager.instance()
            command_manager.update_commands()

            # update playback info
            PlaybackBroadcaster.instance().update_playback_info_cache()
        except Exception as e:
            self.logger.error(f"Error processing update logic: {str(e)}")
