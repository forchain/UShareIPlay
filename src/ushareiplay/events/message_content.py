"""
消息内容事件 - 监控消息内容并处理新消息

当检测到 message_content 元素时，从 page_source 中获取所有消息内容，
记录新消息到日志，并处理命令消息。
"""

__multiple__ = True

import traceback

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.core.chat_intake import QUEUE_COMMAND_PREFIX_CHARS, ChatIntakeKind, classify_chat_line
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
                if content := wrapper.content:
                    content_list.append(content)

            # 获取 MessageManager 实例，使用其 recent_chats
            from ushareiplay.managers.message_manager import MessageManager

            message_manager = MessageManager.instance()

            # 获取聊天日志记录器
            from ushareiplay.managers.message_manager import get_chat_logger

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

            # Fallback: the forward-matching above can fail when content_list
            # contains more items than recent_chats.maxlen (3).  In that case
            # content_list[0] is older than anything in recent_chats and every
            # alignment attempt mismatches at j=0.  Check whether the anchor
            # (recent_chats[-1]) actually *is* visible on screen; if so, we
            # are not truly "missed" — only the window is wider than maxlen.
            if missed and recent_len > 0:
                last_recent = message_manager.recent_chats[-1]
                for idx, content in enumerate(content_list):
                    if content == last_recent:
                        # Anchor visible — override missed.
                        missed = False
                        message_manager.latest_chats.clear()
                        for new_content in content_list[idx + 1:]:
                            message_manager.latest_chats.append(new_content)
                        break

            # 处理所有消息元素
            for content in message_manager.latest_chats:
                result = classify_chat_line(content)

                is_return = result.kind == ChatIntakeKind.USER_RETURN
                if is_return:
                    self.logger.critical(f"User returned: {result.nickname}")
                    await self._notify_user_return(result.nickname)

                if result.kind == ChatIntakeKind.KEYWORD_MENTION:
                    from ushareiplay.managers.keyword_manager import KeywordManager
                    keyword_manager = KeywordManager.instance()

                    keyword_record = await keyword_manager.find_keyword(result.text, result.nickname)
                    if keyword_record:
                        await keyword_manager.execute_keyword(
                            keyword_record,
                            result.nickname,
                            params=result.params,
                            sleep_exempt=True,
                        )
                    else:
                        await keyword_manager.execute_default_keyword(
                            result.nickname,
                            params=result.params,
                            sleep_exempt=True,
                        )

                    chat_logger.critical(content)
                    continue

                if result.kind == ChatIntakeKind.COMMAND:
                    if result.text.strip(QUEUE_COMMAND_PREFIX_CHARS).strip():
                        has_command_message = True
                        chat_logger.critical(content)
                    else:
                        chat_logger.info(content)
                    continue

                chat_logger.info(content)

            handled = False
            # 如果有命令消息，调用 get_latest_messages 获取命令
            if has_command_message:
                await message_manager.process_new_messages()
            else:
                await self._process_update_logic()

            if missed:
                await message_manager.process_missed_messages()
                # After processing, the view has changed (scrolled back to
                # bottom via send_message).  Clear recent_chats so the next
                # iteration starts fresh instead of re-detecting a stale gap.
                message_manager.recent_chats.clear()

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
        """处理更新逻辑（、播放信息等）- 在没有命令消息时执行"""
        try:
            # Update all commands
            command_manager = CommandManager.instance()
            command_manager.update_commands()

            # update playback info
            PlaybackBroadcaster.instance().update_playback_info_cache()
        except Exception as e:
            self.logger.error(f"Error processing update logic: {str(e)}")
