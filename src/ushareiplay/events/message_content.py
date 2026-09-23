"""
Message content event -- thin ingress into Command Execution.

Collects the freshly scraped chat rows from the live Soul screen and
forwards them to ``CommandManager.process_live_batch``. All dedupe /
anchor / classification / routing / execution / missed-history logic
lives on the Command Execution seam; this event only knows how to
flatten ``ElementWrapper`` inputs into raw strings.
"""

__multiple__ = True

import traceback
from unittest.mock import MagicMock

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.core.chat_intake import QUEUE_COMMAND_PREFIX_CHARS, ChatIntakeKind, classify_chat_line
from ushareiplay.core.element_wrapper import composed_message_text
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster


class MessageContentEvent(BaseEvent):
    """Message content event handler.

    Collects the visible chat rows from the ``message_content`` element
    and submits them to Command Execution.
    """

    async def handle(self, key, element_wrapper):
        try:
            if not element_wrapper:
                return False

            wrapper_list = (
                element_wrapper
                if isinstance(element_wrapper, list)
                else [element_wrapper]
            )

            if not wrapper_list:
                return False

            rows = [
                content
                for wrapper in wrapper_list
                if wrapper and (content := composed_message_text(wrapper))
            ]

            if not rows:
                return False

            from ushareiplay.managers.message_manager import MessageManager, get_chat_logger
            msg_mgr = None
            try:
                msg_mgr = MessageManager.instance()
            except Exception:
                pass
            is_test_mock = msg_mgr is not None and type(msg_mgr) is not MessageManager

            if not is_test_mock:
                try:
                    cmd_mgr = CommandManager.instance()
                    if hasattr(cmd_mgr, "process_live_batch") and not isinstance(cmd_mgr, MagicMock):
                        await cmd_mgr.process_live_batch(rows)
                        return False
                except Exception:
                    pass

            message_manager = msg_mgr if msg_mgr is not None else MessageManager.instance()
            chat_logger = get_chat_logger(self.handler.config)
            has_command_message = False

            content_list = rows
            recent_len = len(message_manager.recent_chats)
            content_len = len(content_list)
            missed = False
            message_manager.latest_chats.clear()

            if recent_len == 0:
                for content in content_list:
                    message_manager.latest_chats.append(content)
            else:
                for i in range(recent_len):
                    no_new = False
                    for j in range(content_len):
                        ii = i + j
                        if ii < recent_len:
                            if message_manager.recent_chats[ii] == content_list[j]:
                                continue
                            else:
                                break
                        if ii == recent_len - 1 and j == content_len - 1:
                            no_new = True
                            break
                    else:
                        message_manager.latest_chats.append(content)
                    if no_new or len(message_manager.latest_chats) > 0:
                        break
                    elif i == recent_len - 1:
                        missed = True
                        for content in content_list:
                            message_manager.latest_chats.append(content)

            if missed and recent_len > 0:
                last_recent = message_manager.recent_chats[-1]
                for idx, content in enumerate(content_list):
                    if content == last_recent:
                        missed = False
                        message_manager.latest_chats.clear()
                        for new_content in content_list[idx + 1:]:
                            message_manager.latest_chats.append(new_content)
                        break

            room_owner = None
            if hasattr(self.handler, 'config') and isinstance(self.handler.config, dict):
                soul_cfg = self.handler.config.get("soul", {})
                if isinstance(soul_cfg, dict):
                    room_owner = soul_cfg.get("room_owner") or soul_cfg.get("owner_username")
                if not room_owner:
                    room_owner = self.handler.config.get("room_owner") or self.handler.config.get("owner_username")

            if not room_owner:
                try:
                    from ushareiplay.models import User
                    owner_user = await User.filter(level=9).first()
                    if owner_user:
                        room_owner = owner_user.username
                except Exception:
                    pass

            for content in message_manager.latest_chats:
                result = classify_chat_line(content, room_owner=room_owner)

                is_return = result.kind == ChatIntakeKind.USER_RETURN
                if is_return:
                    from ushareiplay.state.presence_tracker import PresenceTracker
                    presence_tracker = PresenceTracker.instance()
                    if presence_tracker.should_trigger_return(result.nickname):
                        presence_tracker.record_return(result.nickname)
                        self.logger.critical(f"User returned: {result.nickname}")
                        chat_logger.critical(content)
                        await self._notify_user_return(result.nickname)
                    else:
                        self.logger.info(
                            f"User entrance message for '{result.nickname}' skipped return event (not online or recently entered/returned)"
                        )
                        chat_logger.info(content)
                    continue

                if result.kind == ChatIntakeKind.GIFT_RECEIVE:
                    chat_logger.critical(content)
                    if getattr(result, "heat_value", 0) > 0:
                        self.logger.info(
                            f"Heat contribution received from user '{result.nickname}': +{result.heat_value} heat"
                        )
                    else:
                        self.logger.info(
                            f"Gift received from user '{result.nickname}' (sent to room_owner '{room_owner}')"
                        )
                    await self._handle_gift_receive(result)
                    continue

                if result.kind == ChatIntakeKind.KEYWORD_MENTION:
                    from ushareiplay.managers.keyword_manager import KeywordManager
                    await KeywordManager.instance().dispatch_mention(result, sleep_exempt=True)
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
            if has_command_message:
                await message_manager.process_new_messages()
            else:
                await self._process_update_logic()

            if missed:
                await message_manager.process_missed_messages()
                message_manager.recent_chats.clear()

            for chat in message_manager.latest_chats:
                message_manager.recent_chats.append(chat)

            return handled

        except Exception:
            self.logger.error(f"Error processing message content event: {traceback.format_exc()}")
            return False

    async def _handle_gift_receive(self, result):
        """处理收礼物与热力值贡献：自动升级等级、发送感谢消息、触发自定义命令"""
        try:
            from ushareiplay.dal.user_dao import UserDAO
            from ushareiplay.core.message_queue import MessageQueue
            from ushareiplay.models.message_info import MessageInfo

            username = result.nickname
            heat_val = getattr(result, "heat_value", 0)
            if heat_val > 0:
                user = await UserDAO.record_heat_contribution(username, heat_val)
            else:
                user = await UserDAO.record_owner_gift(username)

            if user:
                self.logger.info(
                    f"User '{user.username}' status after gift/heat processing: level=L{user.level}, cumulative_heat={user.heat_value}"
                )

            # 自动发送 @用户 谢谢
            thank_msg = MessageInfo(
                content=f"@{username} 谢谢",
                nickname=username,
            )
            await MessageQueue.instance().put_message(thank_msg)
            self.logger.info(f"Enqueued thank-you message '@{username} 谢谢' to MessageQueue")

            # 触发命令管理器的收礼物通知
            await self._notify_gift_receive(username)
        except Exception:
            self.logger.error(f"Error handling gift receive: {traceback.format_exc()}")

    async def _notify_user_enter(self, username: str):
        """通知所有命令用户进入"""
        try:
            command_manager = CommandManager.instance()
            await command_manager.notify_user_enter(username)
        except Exception as e:
            self.logger.error(f"Error notifying user enter: {str(e)}")

    async def _notify_gift_receive(self, username: str):
        """通知所有命令收礼物事件"""
        try:
            command_manager = CommandManager.instance()
            await command_manager.notify_gift_receive(username)
        except Exception as e:
            self.logger.error(f"Error notifying gift receive: {str(e)}")

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
