"""
消息获取与补漏（MessageManager）

"""
import logging
import os
import traceback
from collections import deque

from selenium.common.exceptions import StaleElementReferenceException

from ushareiplay.core.chat_intake import QUEUE_COMMAND_PREFIX_CHARS, ChatIntakeKind, classify_chat_line
from ushareiplay.core.log_formatter import ColoredFormatter
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.recovery_manager import RecoveryManager
from ushareiplay.models.message_info import MessageInfo


# Global chat logger - will be initialized when needed
chat_logger = None


def get_chat_logger(config=None):
    """Get or create chat logger with configurable directory"""
    global chat_logger
    if chat_logger is None:
        from ushareiplay.core.log_rotation import archive_active_log_on_startup
        from ushareiplay.core.paths import ensure_dir, resolve_log_directory

        cfg = config
        if not ((cfg or {}).get("logging", {}) or {}).get("directory", None):
            from ushareiplay.core.config_loader import ConfigLoader
            loaded = ConfigLoader.load_config()
            if loaded:
                cfg = loaded
        configured = ((cfg or {}).get("logging", {}) or {}).get("directory", "")
        log_dir_path = resolve_log_directory(configured, default_rel="logs")
        ensure_dir(log_dir_path)
        # Create chat logger
        chat_logger = logging.getLogger('chat')
        chat_logger.setLevel(logging.INFO)
        # Clear any existing handlers
        if chat_logger.hasHandlers():
            chat_logger.handlers.clear()
        log_file = archive_active_log_on_startup(log_dir_path, "chat.log")
        handler = logging.FileHandler(log_file, encoding='utf-8')
        # Use ColoredFormatter without colors for file logging
        formatter = ColoredFormatter(
            fmt='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%m-%d %H:%M:%S',
            use_colors=False
        )
        handler.setFormatter(formatter)
        chat_logger.addHandler(handler)
    return chat_logger


class MessageManager(Singleton):
    def __init__(self):
        """Initialize MessageManager with handler, previous messages, recent messages"""
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self._chat_logger = None
        self._recovery_manager = RecoveryManager.instance()

        self.previous_messages = {}
        self.recent_chats = deque(maxlen=3)  # Keep track of recent messages to avoid duplicates
        self.latest_chats = deque(maxlen=3)

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def chat_logger(self):
        """延迟获取 chat_logger 实例"""
        if self._chat_logger is None:
            self._chat_logger = get_chat_logger(self.handler.config)
        return self._chat_logger

    def _get_seat_manager(self):
        """Get the seat_manager lazily to avoid circular import issues"""
        from ushareiplay.managers.seat_manager import SeatManager
        return SeatManager.get_instance()

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

        # scroll back to the missing element
        self.handler.logger.critical(f"last_chat={last_chat}")

        key, element, attribute_values = self.handler.gesture_handler.scroll_container_until_element(
            'message_content',
            'message_list',
            'down',
            'content-desc|text',
            last_chat,
        )

        # send empty message to scroll to bottom instantly (always, even if
        # the anchor was not found — otherwise the view stays on old messages)
        self.handler.send_message("")

        if not key:
            return None

        command_set = set[str]()
        nickname_map = {}

        missed_chats = set[str]()
        for chat in attribute_values:
            if last_chat == chat:
                continue

            is_missed = False
            if chat not in self.recent_chats and chat not in self.latest_chats and chat not in missed_chats:
                self.chat_logger.warning(chat)
                missed_chats.add(chat)
                is_missed = True

            result = classify_chat_line(chat)

            if result.kind == ChatIntakeKind.KEYWORD_MENTION and is_missed:
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
        if not self.handler.key_actions.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        from ushareiplay.managers.command_manager import CommandManager
        command_manager = CommandManager.instance()
        return await command_manager.execute_chat_scan(self.latest_chats)
