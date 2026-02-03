"""
消息内容事件 - 监控消息内容并处理新消息

当检测到 message_content 元素时，从 page_source 中获取所有消息内容，
记录新消息到日志，并处理命令消息。
"""

__multiple__ = True

import re
import traceback

from ..core.base_event import BaseEvent
from ..managers.command_manager import CommandManager
from ..managers.info_manager import InfoManager


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
                if content := wrapper.content:
                    content_list.append(content)

            # 获取 MessageManager 实例，使用其 recent_chats
            from ..managers.message_manager import MessageManager

            message_manager = MessageManager.instance()

            # 获取聊天日志记录器
            from ..managers.message_manager import get_chat_logger

            chat_logger = get_chat_logger(self.handler.config)

            # 标记是否有命令消息
            has_command_message = False

            message_manager.latest_chats.clear()
            recent_len = len(message_manager.recent_chats)
            content_len = len(content_list)
            missed = False
            if recent_len == 0:
                for content in content_list:
                    message_manager.latest_chats.append(content)
            else:
                for i in range(recent_len):
                    no_new = False
                    for j in range(content_len):
                        content = content_list[j]
                        ii = i + j
                        if ii < recent_len:
                            recent_chat = message_manager.recent_chats[ii]
                            if content != recent_chat:
                                break
                            if ii == recent_len - 1 and j == content_len - 1:
                                no_new = True
                                break
                        else:
                            message_manager.latest_chats.append(content)
                    if no_new:
                        break
                    if len(message_manager.latest_chats) > 0:
                        break
                    elif i == recent_len - 1:
                        missed = True
                        for content in content_list:
                            message_manager.latest_chats.append(content)

            # 处理所有消息元素
            for content in message_manager.latest_chats:

                # 检查用户返回消息（原“进来陪你聊天啦/坐着xx来啦”为返回场景，仅触发返回事件，避免与进入事件冗余）
                is_return, username = message_manager.is_user_return_message(content)
                if is_return:
                    self.logger.critical(f"User returned: {username}")
                    await self._notify_user_return(username)

                # === 新增：检查 @我 + 关键字格式 ===
                at_pattern = r"souler\[(.+)\]说：@我\s+(.+)"
                at_match = re.match(at_pattern, content)
                if at_match:
                    username = at_match.group(1)
                    keyword_text = at_match.group(2).strip()

                    # 关键词空格后续的都是参数，例如 "播放 周杰伦 稻香" -> keyword="播放", params="周杰伦 稻香"
                    parts = keyword_text.split(None, 1)
                    keyword = parts[0] if parts else ""
                    params = parts[1] if len(parts) > 1 else ""

                    # 查找并执行关键字
                    from ..managers.keyword_manager import KeywordManager
                    keyword_manager = KeywordManager.instance()

                    keyword_record = await keyword_manager.find_keyword(keyword, username)
                    if keyword_record:
                        # 找到匹配的关键字，执行（command 中可用 {user_name}、{params} 占位符）
                        await keyword_manager.execute_keyword(keyword_record, username, params=params)
                    else:
                        # 没有匹配，执行默认关键字
                        await keyword_manager.execute_default_keyword(username, params=params)

                    chat_logger.critical(content)
                    continue  # 跳过后续的命令检测

                # 检查是否满足命令格式
                pattern = r"souler\[.+\]说：(:.+)"
                match = re.match(pattern, content)
                if match:
                    # 标记有命令消息
                    has_command_message = True
                    chat_logger.critical(content)
                else:
                    chat_logger.info(content)

            handled = False
            # 如果有命令消息，调用 get_latest_messages 获取命令
            if has_command_message:
                await message_manager.process_new_messages()
            else:
                await self._process_update_logic()

            if missed:
                await message_manager.process_missed_messages()

            for chat in message_manager.latest_chats:
                message_manager.recent_chats.append(chat)

            return handled

        except Exception:
            self.logger.error(f"Error processing message content event: {traceback.format_exc()}")
            return False

    async def _notify_user_enter(self, username: str):
        """通知所有命令用户进入"""
        try:
            command_manager = CommandManager.instance()
            await command_manager.notify_user_enter(username)
        except Exception as e:
            self.logger.error(f"Error notifying user enter: {str(e)}")

    async def _notify_user_return(self, username: str):
        """通知所有命令用户返回"""
        try:
            command_manager = CommandManager.instance()
            await command_manager.notify_user_return(username)
        except Exception as e:
            self.logger.error(f"Error notifying user return: {str(e)}")

    async def _process_update_logic(self):
        """处理更新逻辑（定时器、播放信息等）- 在没有命令消息时执行"""
        try:
            # Process queue messages (timer messages, etc.)
            await self._process_queue_messages()

            # Update all commands
            command_manager = CommandManager.instance()
            command_manager.update_commands()

            # update playback info
            info_manager = InfoManager.instance()
            info_manager.update_playback_info_cache()
        except Exception as e:
            self.logger.error(f"Error processing update logic: {str(e)}")

    async def _process_queue_messages(self):
        """处理异步队列中的消息（定时器消息等）
        
        统一处理流程：
        1. 消息保留完整格式（包括 : 前缀和 ; 分隔符）
        2. 检测到 : 前缀后，去掉冒号
        3. 调用 handle_message_commands 处理（不含冒号）
        4. 非命令消息直接发送
        """
        try:
            from ..core.message_queue import MessageQueue
            from ..models.message_info import MessageInfo
            import traceback

            message_queue = MessageQueue.instance()

            # 获取队列中的所有消息
            queue_messages = await message_queue.get_all_messages()
            if not queue_messages:
                return

            self.logger.info(f"Processing {len(queue_messages)} queue messages")

            # 处理每条队列消息
            command_messages = []

            for msg_id, message_info in queue_messages.items():
                # 分割多命令/消息（用分号分隔）
                parts = message_info.content.split(';')

                for idx, part in enumerate(parts):
                    part = part.strip()
                    if not part:
                        continue

                    # 替换占位符
                    part = part.replace('{user_name}', message_info.nickname)

                    if part.startswith(':'):
                        cmd_msg = MessageInfo(
                            content=part,
                            nickname=message_info.nickname
                        )
                        command_messages.append(cmd_msg)
                    else:
                        # 普通消息：直接发送
                        self.handler.send_message(part)

            # 批量处理命令消息
            if command_messages:
                command_manager = CommandManager.instance()
                await command_manager.handle_message_commands(command_messages)

        except Exception:
            self.logger.error(f"Error processing queue messages: {traceback.format_exc()}")
