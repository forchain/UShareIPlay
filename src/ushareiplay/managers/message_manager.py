"""
MessageManager -- chat transport adapter.

Cursor state (recent_chats / latest_chats), dedupe / anchor matching,
Chat Intake classification, command routing, and missed-history recovery
are unified on the Command Execution seam (CommandManager). This module
maintains transport-layer responsibilities: chat-logger setup,
the seat-manager handle for collapsing the seat panel, and the
``party_id`` lookup, while preserving cursor and recovery methods for
compatibility.
"""

from collections import deque
import logging
import traceback

from ushareiplay.core.chat_intake import (
    QUEUE_COMMAND_PREFIX_CHARS,
    ChatIntakeKind,
    classify_chat_line,
    strip_quoted_segment,
)
from ushareiplay.core.log_formatter import ColoredFormatter
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.models.message_info import MessageInfo


# Global chat logger - will be initialized when needed
chat_logger = None


def get_chat_logger(config=None):
    """Get or create chat logger.

    Delegates to the RuntimeLogging module so the chat log inherits the
    same path / archive / handler / reset invariants as the app log.
    """
    global chat_logger
    if chat_logger is None:
        from ushareiplay.core.runtime_logging import get_runtime_logging

        chat_logger = get_runtime_logging().attach_chat_logger(config)
    return chat_logger


class MessageManager(Singleton):
    """Chat transport adapter with compatibility affordances.

    Maintains transport-layer responsibilities (chat logger, seat manager,
    party id) along with compatibility shims for message processing and
    missed-history recovery.
    """

    def __init__(self):
        self._handler = None
        self._chat_logger = None
        self.recent_chats = deque(maxlen=3)
        self.latest_chats = deque(maxlen=3)

    @property
    def handler(self):
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler

            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def chat_logger(self):
        if self._chat_logger is None:
            self._chat_logger = get_chat_logger(self.handler.config)
        return self._chat_logger

    def _get_seat_manager(self):
        from ushareiplay.managers.seat_manager import SeatManager

        return SeatManager.get_instance()

    def get_room_owner(self) -> str | None:
        if hasattr(self.handler, 'config') and isinstance(self.handler.config, dict):
            soul_cfg = self.handler.config.get("soul", {})
            if isinstance(soul_cfg, dict):
                owner = soul_cfg.get("room_owner") or soul_cfg.get("owner_username")
                if owner:
                    return owner
            return self.handler.config.get("room_owner") or self.handler.config.get("owner_username")
        return None

    def get_party_id(self):
        party_id = self.handler.party_id
        if not party_id:
            party_id = self.handler.config['default_party_id']
        return party_id

    async def process_missed_messages(self):
        if not self.handler.key_actions.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        # 回溯补漏前，确保座位面板收起（避免聊天区域过小导致回溯变慢）
        try:
            seat_manager = self._get_seat_manager()
            if seat_manager:
                await seat_manager.prepare_for_chat_scan()
        except Exception:
            self.handler.logger.error(f"收起座位失败（不影响补漏继续执行）: {traceback.format_exc()}")

        last_chat = self.recent_chats[-1] if len(self.recent_chats) > 0 else None
        if not last_chat:
            return None

        # Quoted Messages are composed onto the scanned line but never rendered
        # in the sender's own bubble, so scroll/skip on the quote-free line.
        anchor = strip_quoted_segment(last_chat) or last_chat

        # scroll back to the missing element
        self.handler.logger.critical(f"last_chat={last_chat}")

        key, element, attribute_values = self.handler.gesture_handler.scroll_container_until_element(
            'message_content',
            'message_list',
            'down',
            'content-desc|text',
            anchor,
        )

        # send empty message to scroll to bottom instantly (always, even if
        # the anchor was not found — otherwise the view stays on old messages)
        self.handler.send_message("")

        if not key:
            return None

        command_set = set[str]()
        nickname_map = {}

        room_owner = self.get_room_owner()
        missed_chats = set[str]()
        # Scanned lines carry no quote; compare on the quote-free form of what we
        # already processed so a reply is not re-reported (and re-dispatched).
        known_chats = {strip_quoted_segment(chat) for chat in self.recent_chats}
        known_chats.update(strip_quoted_segment(chat) for chat in self.latest_chats)
        for chat in attribute_values:
            if anchor == strip_quoted_segment(chat):
                continue

            is_missed = False
            if chat not in known_chats and chat not in missed_chats:
                self.chat_logger.warning(chat)
                missed_chats.add(chat)
                is_missed = True

            result = classify_chat_line(chat, room_owner=room_owner)

            if result.kind == ChatIntakeKind.KEYWORD_MENTION and is_missed:
                from ushareiplay.managers.keyword_manager import KeywordManager
                await KeywordManager.instance().dispatch_mention(result, sleep_exempt=True)

                continue

            if result.kind == ChatIntakeKind.GIFT_RECEIVE and is_missed:
                from ushareiplay.dal.user_dao import UserDAO
                from ushareiplay.managers.command_manager import CommandManager

                username = result.nickname
                heat_val = getattr(result, "heat_value", 0)
                if heat_val > 0:
                    user = await UserDAO.record_heat_contribution(username, heat_val)
                    if user:
                        self.handler.logger.info(
                            f"Missed heat contribution processed for user '{user.username}': level=L{user.level}, cumulative_heat={user.heat_value}"
                        )
                else:
                    user = await UserDAO.record_owner_gift(username)
                    if user:
                        self.handler.logger.info(
                            f"Missed gift processed for user '{user.username}': level=L{user.level}"
                        )

                thank_msg = MessageInfo(
                    content=f"@{username} 谢谢",
                    nickname=username,
                )
                await MessageQueue.instance().put_message(thank_msg)
                self.handler.logger.info(f"Enqueued thank-you message '@{username} 谢谢' to MessageQueue")
                await CommandManager.instance().notify_gift_receive(username)
                continue

            if result.kind == ChatIntakeKind.COMMAND:
                command = result.text
                if not command.strip(QUEUE_COMMAND_PREFIX_CHARS).strip():
                    continue
                command_set.add(command)
                nickname_map[command] = result.nickname

        message_queue = MessageQueue.instance()
        for command in command_set:
            message = MessageInfo(command, nickname_map[command])
            await message_queue.put_message(message)
            self.handler.logger.info(f"Missed command added to queue: {command}")

        return command_set

    async def process_new_messages(self):
        """Compatibility shim.

        Delegates to ``CommandManager`` so legacy callers (and the
        Soul-handler lookup) continue to work; new code should call
        ``CommandManager.process_live_batch(rows)`` directly.
        """
        from ushareiplay.managers.command_manager import CommandManager

        return await CommandManager.instance().execute_chat_scan(self.latest_chats)
