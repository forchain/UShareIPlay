import logging
import re
import traceback
from collections import deque
from dataclasses import dataclass

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import StaleElementReferenceException

from .greeting_manager import GreetingManager


# Global chat logger - will be initialized when needed
chat_logger = None


def get_chat_logger(config=None):
    """Get or create chat logger with configurable directory"""
    global chat_logger
    import yaml, os
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
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%m-%d %H:%M:%S'))
        chat_logger.addHandler(handler)
    return chat_logger


@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    avatar_element: object  # WebElement for avatar, always exists
    relation_tag: bool = False  # True if user has relation tag


class MessageManager:
    def __init__(self, handler):
        """Initialize MessageManager with handler, previous messages, recent messages"""
        self.handler = handler
        self.previous_messages = {}
        self.recent_messages = deque(maxlen=3)  # Keep track of recent messages to avoid duplicates
        self.greeting_manager = GreetingManager(handler)

        # Initialize chat logger with config
        self.chat_logger = get_chat_logger(handler.config)

    def _get_seat_manager(self):
        """Get the seat_manager lazily to avoid circular import issues"""
        from ..managers.seat_manager import seat_manager
        return seat_manager

    def get_party_id(self):
        party_id = self.handler.party_id
        if not party_id:
            party_id = self.handler.config['default_party_id']
        return party_id

    async def get_latest_message(self, enabled=True):
        """Get new message contents that weren't seen before"""
        if not self.handler.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        # Get message list container
        message_list = self.handler.try_find_element_plus('message_list', log=False)
        if not message_list:
            self.handler.logger.error("Failed to find message list")
            return None

        # Collapse seats if expanded and update focus count
        seat_manager = self._get_seat_manager()

        # 更新焦点计数
        if seat_manager and hasattr(seat_manager, 'focus'):
            # self.handler.logger.info("更新焦点计数...")
            seat_manager.focus.update()

        # Get all ViewGroup containers
        try:
            containers = message_list.find_elements(AppiumBy.CLASS_NAME, "android.view.ViewGroup")
        except Exception as e:
            self.handler.logger.error(f'cannot find message_list element, might be in loading')
            return None

        # Process each container and collect message info
        current_messages = {}  # Dict to store element_id: MessageInfo pairs

        for container in containers:
            message_info = await self.process_container_message(container)
            greeting_info = await self.greeting_manager.process_container_greeting(container)

            if message_info:
                current_messages[container.id] = message_info
            if greeting_info:
                current_messages[container.id] = greeting_info

        # Update previous message IDs and return new messages
        new_messages = {}  # Changed from list to dict
        for element_id, message_info in current_messages.items():
            if element_id not in self.previous_messages:
                new_messages[element_id] = message_info  # Store as dict

        self.previous_messages = current_messages
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

    async def process_container_message(self, container):
        """Process a single message container and return MessageInfo"""
        try:
            # Check if container has valid message content
            content_element = self.handler.find_child_element_plus(
                container,
                'message_content'
            )
            if not content_element:
                return None

            message_text = content_element.text
            content_desc = self.handler.try_get_attribute(content_element, 'content-desc')
            chat_text = content_desc if content_desc and content_desc != 'null' else message_text

            # Check if container has valid sender avatar

            # Check for duplicate message
            if not chat_text in self.recent_messages:
                is_enter, username = self.is_user_enter_message(chat_text)
                if is_enter:
                    self.handler.logger.info(f"User entered: {username}")
                    # Notify all commands
                    for module in self.handler.controller.command_modules.values():
                        try:
                            if hasattr(module.command, 'user_enter'):
                                await module.command.user_enter(username)
                        except Exception as e:
                            self.handler.logger.error(f"Error in command user_enter: {traceback.format_exc()}")
                        continue
                self.chat_logger.info(chat_text)
                self.recent_messages.append(chat_text)

            # Parse message content using pattern
            pattern = r'souler\[.+\]说：:(.+)'
            match = re.match(pattern, chat_text)
            if not match:
                return None

            # Extract actual message content
            message_content = match.group(1).strip()

            # Get avatar element
            avatar_element = self.handler.find_child_element_plus(
                container,
                'sender_avatar'
            )
            if not avatar_element:
                return None

            # Get nickname
            nickname_element = self.handler.find_child_element_plus(
                container,
                'sender_nickname'
            )
            nickname = nickname_element.text if nickname_element else "Unknown"

            # Check for relation tag
            relation_tag = bool(self.handler.find_child_element_plus(
                container,
                'sender_relation'
            ))

            return MessageInfo(message_content, nickname, avatar_element, relation_tag)

        except StaleElementReferenceException:
            self.handler.logger.warning("Message element became stale")
            return None
        except Exception as e:
            self.handler.logger.error(f"Error processing message container: {traceback.format_exc()}")
            return None
