import traceback
from dataclasses import dataclass
from selenium.common.exceptions import StaleElementReferenceException
from appium.webdriver.common.appiumby import AppiumBy
import re
from collections import deque
import logging

DEFAULT_PARTY_ID = "FM15321640"  # Default party ID to join
DEFAULT_NOTICE = "U Share I Play\n分享音乐 享受快乐"  # Default party ID to join

# Set up chat logger
chat_logger = logging.getLogger('chat')
chat_logger.setLevel(logging.INFO)
handler = logging.FileHandler('logs/chat.log', encoding='utf-8')
handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%m-%d %H:%M:%S'))
chat_logger.addHandler(handler)

@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    avatar_element: object  # WebElement for avatar, always exists
    relation_tag: bool = False  # True if user has relation tag


class MessageManager:
    def __init__(self, handler):
        self.handler = handler
        self.previous_message_ids = set()
        self.recent_messages = deque(maxlen=9)  # Keep last 9 messages

    def get_latest_message(self, enabled=True):
        """Get new message contents that weren't seen before"""
        if not self.handler.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        # Get message list container
        message_list = self.try_find_message_list(enabled)
        if not message_list:
            return None

        # Check if there is a new message tip and click it
        self.check_new_message_tip(enabled)

        # Collapse seats if expanded
        self.collapse_seats()

        # Get all ViewGroup containers
        try:
            containers = message_list.find_elements(AppiumBy.CLASS_NAME, "android.view.ViewGroup")
        except Exception as e:
            self.handler.logger.error(f'cannot find message_list element, might be in loading')
            return None

        # Process each container and collect message info
        current_messages = {}  # Dict to store element_id: MessageInfo pairs

        for container in containers:
            message_info = self.process_container_message(container)
            greeting_info = self.process_container_greeting(container)
            if message_info:
                current_messages[container.id] = message_info
            if greeting_info:
                current_messages[container.id] = greeting_info

        # Update previous message IDs and return new messages
        new_messages = {}  # Changed from list to dict
        for element_id, message_info in current_messages.items():
            if element_id not in self.previous_message_ids:
                new_messages[element_id] = message_info  # Store as dict
                self.previous_message_ids.add(element_id)

        return new_messages if new_messages else None

    def try_find_message_list(self, enabled):
        """Find and return message list container"""
        message_list = self.handler.try_find_element_plus('message_list')

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

            self.handler.controller.seat_command.be_seated()
            self.handler.controller.notice_command.change_notice(DEFAULT_NOTICE)
        else:
            self.handler.logger.warning(
                "still cannot find message_list, may stay in unknown pages, go back first")
            self.handler.press_back()

    def check_new_message_tip(self, enabled):
        """Check and click new message tip if present"""
        new_message_tip = self.handler.try_find_element_plus('new_message_tip', log=False)
        if new_message_tip and enabled:
            self.handler.logger.info(f'Found new message tip')
            new_message_tip.click()
            self.handler.logger.info(f'Clicked new message tip')

    def collapse_seats(self):
        """Collapse seats if expanded"""
        expand_seats = self.handler.try_find_element_plus('expand_seats', log=False)
        if expand_seats and expand_seats.text == '收起座位':
            expand_seats.click()
            self.handler.logger.info(f'Collapsed seats')

    def process_container_message(self, container):
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
            # Get message content from content-desc attribute

            # Check for duplicate message
            if not chat_text in self.recent_messages:
                chat_logger.info(chat_text)
                self.recent_messages.append(chat_text)

            # Parse message content using pattern
            # pattern = r'souler\[.+\]说：:(.+)'
            pattern = r':(.+)'
            match = re.match(pattern, message_text)
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

    def process_container_greeting(self, container):
        """Process greeting for follower entering room"""
        try:
            # Check if container has follower message content
            follower_message = self.handler.find_child_element_plus(
                container,
                'follower_message'
            )
            if not follower_message:
                return None

            message_text = follower_message.text
            # Click the message at 25% from top
            if not self.handler.click_element_at(follower_message, y_ratio=0.25):
                return None
            self.handler.logger.info("Clicked follower message")

            # Wait for follow status and check
            follow_status = self.handler.wait_for_element_clickable_plus('follow_status')
            if not follow_status or follow_status.text == '关注':
                self.handler.logger.info("User not followed or left, canceling")
                self.handler.press_back()
                return None

            # Click send gift button
            send_gift = self.handler.wait_for_element_clickable_plus('send_gift')
            if not send_gift:
                self.handler.logger.error("Failed to find send gift button")
                return None
            send_gift.click()
            self.handler.logger.info("Clicked send gift")

            # Wait for give gift button to ensure gift panel loaded
            give_gift = self.handler.wait_for_element_clickable_plus('give_gift')
            if not give_gift:
                self.handler.logger.error("Failed to find give gift button")
                self.handler.press_back()
                return None

            # Try to find and send soul power gift
            soul_power = self.handler.try_find_element_plus('soul_power', log=False)
            if soul_power:
                # Click give gift button to send
                give_gift.click()
                self.handler.logger.info("Sent soul power gift")
            else:
                # If no gift available, try to greet
                self.handler.press_back()  # Close gift panel
                greet_follower = self.handler.wait_for_element_clickable_plus('greet_follower')
                if not greet_follower:
                    self.handler.logger.error("Failed to find greet button")
                    return None

                greet_follower.click()
                self.handler.logger.info("Clicked greet button")

                # Wait and click send message button
                send_button = self.handler.wait_for_element_clickable_plus('button_send')
                if not send_button:
                    self.handler.logger.error("Failed to find send message button")
                    return None
                send_button.click()
                self.handler.logger.info("Sent greeting message")

            return MessageInfo(
                content=message_text,
                nickname="System",
                avatar_element=None,
                relation_tag=False
            )

        except Exception as e:
            self.handler.log_error(f"Error processing greeting: {traceback.format_exc()}")
            return None
