"""
消息获取与补漏（MessageManager）

"""
import logging
import os
import re
import traceback
from collections import deque

from selenium.common.exceptions import StaleElementReferenceException

from ..core.log_formatter import ColoredFormatter
from ..core.message_queue import MessageQueue
from ..core.singleton import Singleton
from ..managers.recovery_manager import RecoveryManager
from ..models.message_info import MessageInfo

# Global chat logger - will be initialized when needed
chat_logger = None


def get_chat_logger(config=None):
    """Get or create chat logger with configurable directory"""
    global chat_logger
    import yaml
    if chat_logger is None:
        # 直接加载全局 config.yaml
        try:
            with open('config.yaml', 'r', encoding='utf-8') as f:
                global_config = yaml.safe_load(f)
            log_dir = global_config.get('logging', {}).get('directory', 'logs')
        except Exception as e:
            print(f"[日志调试] 加载 config.yaml 失败: {e}")
            log_dir = 'logs'
        print(f"[日志调试] chat.log 日志目录: {log_dir}, 绝对路径: {os.path.abspath(log_dir)}")
        # Create logs directory if it doesn't exist (supports relative paths)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        # Create chat logger
        chat_logger = logging.getLogger('chat')
        chat_logger.setLevel(logging.INFO)
        # Clear any existing handlers
        if chat_logger.hasHandlers():
            chat_logger.handlers.clear()
        log_file = f'{log_dir}/chat.log'
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
            from ..handlers.soul_handler import SoulHandler
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
        from .seat_manager import seat_manager
        return seat_manager

    def get_party_id(self):
        party_id = self.handler.party_id
        if not party_id:
            party_id = self.handler.config['default_party_id']
        return party_id

    async def process_missed_messages(self):

        if not self.handler.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        last_chat = self.recent_chats[-1] if len(self.recent_chats) > 0 else None
        if not last_chat:
            return None

        # scroll back to the missing element
        self.handler.logger.critical(f"last_chat={last_chat}")

        key, element, attribute_values = self.handler.scroll_container_until_element(
            'message_content',
            'message_list',
            'down',
            'content-desc|text',
            last_chat,
        )

        # send empty message to scroll to bottom instantly
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

            # Parse @我 keyword messages for missed chats
            at_pattern = r'souler\[(.+)\]说：@我\s+(.+)'
            at_match = re.match(at_pattern, chat)
            if at_match and is_missed:
                username = at_match.group(1).strip()
                keyword_text = at_match.group(2).strip()

                parts = keyword_text.split(None, 1)
                keyword = parts[0] if parts else ""
                params = parts[1] if len(parts) > 1 else ""

                from ..managers.keyword_manager import KeywordManager
                keyword_manager = KeywordManager.instance()

                keyword_record = await keyword_manager.find_keyword(keyword, username)
                if keyword_record:
                    await keyword_manager.execute_keyword(keyword_record, username, params=params)
                else:
                    await keyword_manager.execute_default_keyword(username, params=params)

                continue

            # Parse message content using pattern
            pattern = r'souler\[(.+)\]说：(:.+)'

            match = re.match(pattern, chat)
            if not match:
                continue

            # Extract actual message content
            nickname = match.group(1).strip()
            command = match.group(2).strip()
            command_set.add(command)
            nickname_map[command] = nickname

        message_queue = MessageQueue.instance()
        for command in command_set:
            message = MessageInfo(command, nickname_map[command])
            await message_queue.put_message(message)
            self.handler.logger.info(f"Missed command added to queue: {command}")

        return command_set

    async def process_new_messages(self):
        if not self.handler.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        messages = []
        for chat in self.latest_chats:
            pattern = r'souler\[(.+)\]说：(:.+)'

            match = re.match(pattern, chat)
            if not match:
                return None

            # Extract actual message content
            nickname = match.group(1).strip()
            message_content = match.group(2).strip()
            message = MessageInfo(message_content, nickname)
            messages.append(message)

        # 有新的命令消息，触发命令处理
        from src.managers.command_manager import CommandManager
        command_manager = CommandManager.instance()
        await command_manager.handle_message_commands(messages)

        return messages

    def is_user_enter_message(self, message: str) -> tuple[bool, str]:
        """Check if message is a user enter notification
        Args:
            message: str, message to check
        Returns:
            tuple[bool, str]: (is_enter_message, username)
        """
        pattern = r"^(.+)(?:进来陪你聊天啦|坐着.+来啦).*?$"
        match = re.match(pattern, message)
        if match:
            return True, match.group(1)
        return False, ""

    def is_user_return_message(self, message: str) -> tuple[bool, str]:
        """Check if message is a user return notification（用户重新打开 app 返回派对时的消息）
        Args:
            message: str, message to check
        Returns:
            tuple[bool, str]: (is_return_message, username)
        """
        pattern = r"^(.+)(?:进来陪你聊天啦|坐着.+来啦).*?$"
        match = re.match(pattern, message)
        if match:
            return True, match.group(1)
        return False, ""
