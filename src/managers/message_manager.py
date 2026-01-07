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

    def is_messages_missed(self):
        if len(self.recent_chats) > 0 and len(self.latest_chats) > 0:
            last_chat = self.recent_chats[-1]
            new_chat = self.latest_chats[0]
            return (last_chat not in self.latest_chats) and (new_chat not in self.recent_chats)

        return False

    async def get_messages_from_containers(self, containers):
        """
        将 UI containers 转成 current_messages/new_messages（用于命令执行）。

        说明：
        - `current_messages` 以 container.id 为 key，值为 MessageInfo（或 greeting_info）。
        - 通过 `previous_messages` 做差集，得到本轮“新增容器”的消息。

        风险点（仅注释，不在此处改行为）：
        - 你这里把 greeting_info 放进 `recent_messages` 的方式用了 walrus 组合表达式，
          很容易把 bool 存进 deque（见下方日志会记录）。
        """
        # Process each container and collect message info
        current_messages = {}  # Dict to store element_id: MessageInfo pairs

        for container in containers:
            command_info = await self.process_container_command(container)
            # Greeting 逻辑已迁移到事件系统，不再需要在这里处理

            if command_info:
                current_messages[container.id] = command_info

        # Update previous message IDs and return new messages
        new_messages = {}  # Changed from list to dict
        for element_id, command_info in current_messages.items():
            if element_id not in self.previous_messages:
                new_messages[element_id] = command_info  # Store as dict

        self.previous_messages = current_messages
        return new_messages if new_messages else None

    async def process_missed_messages(self):
        if not self.handler.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        # Get all ViewGroup containers
        containers = self.handler.find_elements_plus('message_container')

        if len(containers) == 0:
            return None

        last_chat = self.recent_chats[-1] if len(self.recent_chats) > 0 else None

        # scroll back to the missing element
        self.handler.logger.info(f"last_chat={last_chat}")

        key, element, attribute_values = self.handler.scroll_container_until_element(
            'message_content',
            'message_list',
            'down',
            'content-desc|text',
            last_chat,
        )
        if not key:
            return None

        command_set = set[str]()
        nickname_map = {}
        for chat in attribute_values:
            # Parse message content using pattern
            pattern = r'souler\[(.+)\]说：:(.+)'
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
            message = MessageInfo(command, nickname_map[command], None, True)
            await message_queue.put_message(message)
            self.handler.logger.info(f"Missed command added to queue: {command}")

        from .info_manager import InfoManager
        info_manager = InfoManager.instance()
        info_manager.send_playing_message()

        return command_set

    async def get_latest_messages(self):
        """Get new message contents that weren't seen before
        Returns:
            dict: New messages if any found
            None: No new messages (normal state)
            'ABNORMAL_STATE': Unable to access message list (abnormal state)
        """
        if not self.handler.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")

        # Get message list container
        message_list = self.handler.try_find_element_plus('message_list', log=False)
        if not message_list:
            self.handler.logger.error("Failed to find message list")
            return 'ABNORMAL_STATE'

        # 专注数监控已迁移到事件系统，不再需要手动调用

        # Get all ViewGroup containers
        try:
            containers = self.handler.find_elements_plus('message_container')
        except Exception as e:
            self.handler.logger.error('cannot find message_list element, might be in loading')
            return 'ABNORMAL_STATE'

        if len(containers) == 0:
            return None

        # NOTE: get_messages_from_containers 是 async，这里需要 await 才会真正执行。
        # 先加日志观测返回类型；后续根据运行时证据再决定是否统一修正。
        try:
            new_messages = await self.get_messages_from_containers(containers)
        except Exception:
            self.handler.logger.error(f"[messages] no_miss processing failed: {traceback.format_exc()}")
            return 'ABNORMAL_STATE'

        return new_messages if new_messages else None

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

    def get_chat_text(self, container):
        # Check if container has valid message content
        content_element = self.handler.find_child_element_plus(
            container,
            'message_content'
        )
        if not content_element:
            return None

        chat_text = self.handler.try_get_attribute(content_element, 'content-desc')
        if not chat_text or chat_text == 'null':
            try:
                chat_text = content_element.text
            except StaleElementReferenceException:
                chat_text = None
        return chat_text

    async def process_container_command(self, container):
        """Process a single message container and return MessageInfo"""
        try:
            chat_text = self.get_chat_text(container)
            if not chat_text:
                return None

            # Parse message content using pattern
            pattern = r'souler\[(.+)\]说：:(.+)'
            match = re.match(pattern, chat_text)
            if not match:
                return None

            # Extract actual message content
            nickname = match.group(1).strip()
            message_content = match.group(2).strip()

            # Get avatar element
            avatar_element = self.handler.find_child_element_plus(
                container,
                'sender_avatar'
            )
            if not avatar_element:
                return None

            # Check for relation tag
            relation_tag = bool(self.handler.find_child_element_plus(
                container,
                'sender_relation'
            ))

            return MessageInfo(message_content, nickname, avatar_element, relation_tag)

        except StaleElementReferenceException:
            self.handler.logger.warning("Message element became stale")
            return None
        except Exception:
            self.handler.logger.error(f"Error processing message container: {traceback.format_exc()}")
            return None
