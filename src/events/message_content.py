"""
消息内容事件 - 监控消息内容并处理新消息

当检测到 message_content 元素时，从 page_source 中获取所有消息内容，
记录新消息到日志，并处理命令消息。
"""

__multiple__ = True

import asyncio
import os
import re

from ..core.base_event import BaseEvent
from ..managers.command_manager import CommandManager
from ..managers.info_manager import InfoManager
from ..managers.message_manager import MessageManager
from ..managers.recovery_manager import RecoveryManager

# Get project root directory
# Priority: 1. Environment variable DEBUG_LOG_DIR, 2. Relative path from this file
_DEBUG_LOG_DIR = os.environ.get('DEBUG_LOG_DIR')
if _DEBUG_LOG_DIR:
    # Use environment variable if set
    _DEBUG_LOG_DIR = os.path.expanduser(_DEBUG_LOG_DIR)  # Support ~ in path
else:
    # Default: relative path from this file (two levels up)
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    _DEBUG_LOG_DIR = os.path.join(_PROJECT_ROOT, '.cursor')

_DEBUG_LOG_PATH = os.path.join(_DEBUG_LOG_DIR, 'debug.log')

# Ensure .cursor directory exists
if not os.path.exists(_DEBUG_LOG_DIR):
    os.makedirs(_DEBUG_LOG_DIR, exist_ok=True)


class MessageContentEvent(BaseEvent):
    """消息内容事件处理器"""

    def _is_user_enter_message(self, message: str) -> tuple[bool, str]:
        """
        检查消息是否是用户进入通知

        Args:
            message: 消息文本

        Returns:
            tuple[bool, str]: (是否是进入消息, 用户名)
        """
        pattern = r"^(.+)(?:进来陪你聊天啦|坐着.+来啦).*?$"
        match = re.match(pattern, message)
        if match:
            return True, match.group(1)
        return False, ""

    def handle(self, key: str, element_wrapper):
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

            # 获取 MessageManager 实例，使用其 recent_chats
            from ..managers.message_manager import MessageManager

            message_manager = MessageManager.instance()

            # 获取聊天日志记录器
            from ..managers.message_manager import get_chat_logger

            chat_logger = get_chat_logger(self.handler.config)

            # 标记是否有命令消息
            has_command_message = False

            # 处理所有消息元素
            for wrapper in wrapper_list:
                chat_text = wrapper.content
                if not chat_text:
                    continue

                # 检查是否是新消息（使用 message_manager 的 recent_chats）
                if chat_text in message_manager.latest_chats:
                    continue

                # 检查用户进入消息
                is_enter, username = self._is_user_enter_message(chat_text)
                if is_enter:
                    self.logger.critical(f"User entered: {username}")
                    # 通知所有命令
                    asyncio.create_task(self._notify_user_enter(username))

                # 添加到 recent_chats（维护最近的消息列表）
                message_manager.latest_chats.append(chat_text)

                # 检查是否满足命令格式
                pattern = r"souler\[.+\]说：:(.+)"
                match = re.match(pattern, chat_text)
                if match:
                    # 标记有命令消息
                    has_command_message = True
                    chat_logger.critical(chat_text)
                else:
                    chat_logger.info(chat_text)
            
            # #region agent log
            with open(_DEBUG_LOG_PATH, 'a') as f:
                import json
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"message_content.py:110","message":"After processing all messages, checking has_command_message","data":{"has_command_message":has_command_message},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            # #endregion

            # 如果有命令消息，调用 get_latest_messages 获取命令
            if has_command_message:
                # #region agent log
                with open(_DEBUG_LOG_PATH, 'a') as f:
                    import json
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"message_content.py:112","message":"has_command_message is True, calling _process_command_messages","data":{"has_command_message":has_command_message},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                # #endregion
                asyncio.create_task(self._process_command_messages())

            return False

        except Exception as e:
            self.logger.error(f"Error processing message content event: {str(e)}")
            return False

    async def _notify_user_enter(self, username: str):
        """通知所有命令用户进入"""
        try:
            command_manager = CommandManager.instance()
            await command_manager.notify_user_enter(username)
        except Exception as e:
            self.logger.error(f"Error notifying user enter: {str(e)}")

    async def _process_command_messages(self):
        """处理命令消息 - 调用 get_latest_messages 获取命令"""
        try:
            message_manager = MessageManager.instance()

            # 调用 get_latest_messages 获取命令消息
            messages = await message_manager.get_latest_messages()

            # #region agent log
            with open(_DEBUG_LOG_PATH, 'a') as f:
                import json
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B","location":"message_content.py:134","message":"get_latest_messages returned","data":{"messages_type":str(type(messages)),"messages_value":str(messages),"messages_is_none":messages is None,"messages_bool":bool(messages),"messages_eq_abnormal":messages == "ABNORMAL_STATE"},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            # #endregion

            message_manager.recent_chats = message_manager.latest_chats
            message_manager.latest_chats = []

            if messages:
                # #region agent log
                with open(_DEBUG_LOG_PATH, 'a') as f:
                    import json
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B","location":"message_content.py:139","message":"Entered if messages branch","data":{"messages_type":str(type(messages)),"messages_value":str(messages)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                # #endregion
                # 有新的命令消息，触发命令处理
                command_manager = CommandManager.instance()
                await command_manager.handle_message_commands(messages)
            elif messages == "ABNORMAL_STATE":
                # #region agent log
                with open(_DEBUG_LOG_PATH, 'a') as f:
                    import json
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B","location":"message_content.py:143","message":"Entered elif messages == ABNORMAL_STATE branch","data":{},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                # #endregion
                self.handler.press_back()
                self.logger.error(
                    "Failed to get latest messages, press back to exit abnormal state"
                )
            elif messages is None:
                # #region agent log
                with open(_DEBUG_LOG_PATH, 'a') as f:
                    import json
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B","location":"message_content.py:148","message":"Entered elif messages is None branch","data":{},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                # #endregion
                recovery_manager = RecoveryManager.instance()
                if not recovery_manager.manual_mode_enabled:
                    # Process queue messages (timer messages, etc.)
                    await self._process_queue_messages()

                    # Update all commands
                    command_manager = CommandManager.instance()
                    command_manager.update_commands()

                # update playback info
                info_manager = InfoManager.instance()
                info_manager.update_playback_info_cache()

                await asyncio.sleep(1)
                self.logger.error("No new messages")
            else:
                # #region agent log
                with open(_DEBUG_LOG_PATH, 'a') as f:
                    import json
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B","location":"message_content.py:163","message":"None of the branches executed (else branch)","data":{"messages_type":str(type(messages)),"messages_value":str(messages),"messages_is_none":messages is None,"messages_bool":bool(messages)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                # #endregion
        except Exception as e:
            # #region agent log
            with open(_DEBUG_LOG_PATH, 'a') as f:
                import json
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"message_content.py:165","message":"Exception in _process_command_messages","data":{"error":str(e)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            # #endregion
            self.logger.error(f"Error processing command messages: {str(e)}")

    async def _process_queue_messages(self):
        """处理异步队列中的消息（定时器消息等）"""
        try:
            from ..core.message_queue import MessageQueue

            message_queue = MessageQueue.instance()

            # 获取队列中的所有消息
            queue_messages = await message_queue.get_all_messages()
            if queue_messages:
                self.logger.info(f"Processing {len(queue_messages)} queue messages")

                # 通过 CommandManager 处理所有消息
                command_manager = CommandManager.instance()
                response = await command_manager.handle_message_commands(queue_messages)
                if response:
                    self.handler.send_message(response)

        except Exception as e:
            self.logger.error(f"Error processing queue messages: {str(e)}")
