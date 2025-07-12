import traceback
import os
from dataclasses import dataclass
from selenium.common.exceptions import StaleElementReferenceException
from appium.webdriver.common.appiumby import AppiumBy
import re
from collections import deque
import logging

from ..core.base_command import BaseCommand
from .greeting_manager import GreetingManager


DEFAULT_PARTY_ID = "FM15321640"  # Default party ID to join
DEFAULT_NOTICE = "U Share I Play\n分享音乐 享受快乐"  # Default party ID to join

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

    async def get_latest_message(self, enabled=True):
        """Get new message contents that weren't seen before"""
        if not self.handler.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        # Check for QQ Music ANR dialog and handle it
        anr_close = self.handler.try_find_element_plus('close_app', log=False)
        if anr_close:
            anr_close.click()
            self.handler.switch_to_app()

        # Get message list container
        message_list = self.try_find_message_list(enabled)
        if not message_list:
            return None

        # Check if there is a new message tip and click it
        self.check_new_message_tip(enabled)

        # Collapse seats if expanded and update focus count
        # self.handler.logger.info("开始尝试收起座位...")
        seat_manager = self._get_seat_manager()
        if seat_manager is None:
            self.handler.logger.error("seat_manager 为 None，无法收起座位")
        elif not hasattr(seat_manager, 'ui'):
            self.handler.logger.error("seat_manager 没有 ui 属性，无法收起座位")
        elif seat_manager.ui is None:
            self.handler.logger.error("seat_manager.ui 为 None，无法收起座位")
        else:
            # self.handler.logger.info("调用 seat_manager.ui.collapse_seats()...")
            result = seat_manager.ui.collapse_seats()
            # self.handler.logger.info(f"collapse_seats() 返回值: {result}")
            
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

    def try_find_message_list(self, enabled):
        """Find and return message list container"""
        message_list = self.handler.try_find_element_plus('message_list', log=False)

        if not message_list and enabled:
            self.handler.logger.warning("cannot find message_list, may be minimized")
            return self.handle_minimized_state()

        return message_list

    def handle_minimized_state(self):
        """Handle case when message list is minimized"""
        floating_entry = self.handler.try_find_element_plus('floating_entry', clickable=True)
        if floating_entry:
            floating_entry.click()
            return self.handler.try_find_element_plus('message_list')
        else:
            self.handle_navigation_to_party()
            return None

    def handle_navigation_to_party(self):
        """Handle navigation to party when needed"""
        square_tab = self.handler.try_find_element_plus('square_tab')
        if square_tab:
            self.handler.logger.warning(
                "already back in home but no party entry found, try go to party")
            square_tab.click()
            party_id = self.handler.party_id if self.handler.party_id else DEFAULT_PARTY_ID
            self.handler.find_party_to_join(party_id)
            self.handler.party_id = None

            # Get seat manager and use it if available
            seat_manager = self._get_seat_manager()
            if seat_manager and seat_manager.seating:
                seat_manager.seating.find_owner_seat()
                
            self.handler.controller.notice_command.change_notice(DEFAULT_NOTICE)
        else:
            self.handler.logger.warning(
                "still cannot find message_list, may stay in unknown pages, go back first")
            go_back = self.handler.try_find_element_plus('go_back', log=False)
            if go_back:
                go_back.click()
                self.handler.logger.info(f'Clicked go back')
            else:
                self.handler.press_back()

    def check_new_message_tip(self, enabled):
        """Check and click new message tip if present"""
        new_message_tip = self.handler.try_find_element_plus('new_message_tip', log=False)
        if new_message_tip and enabled:
            self.handler.logger.info(f'Found new message tip')
            new_message_tip.click()
            self.handler.logger.info(f'Clicked new message tip')


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
