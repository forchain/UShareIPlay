import traceback
from dataclasses import dataclass
from ..dal import UserDAO
from ..managers.seat_manager import seat_manager
from ..core.singleton import Singleton
from ..managers.sleep_manager import SleepManager

@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    avatar_element: object  # WebElement for avatar, always exists
    relation_tag: bool = False  # True if user has relation tag

class GreetingManager(Singleton):
    def _init(self, handler=None):
        self.handler = handler
        self.sleep_manager = SleepManager(handler)

    async def process_container_greeting(self, container):
        """Process greeting for follower entering room"""
        try:
            # Check if sleep mode is enabled
            if self.sleep_manager.is_sleep_mode_enabled():
                self.handler.logger.info("Sleep mode is enabled, skipping greeting")
                return None

            # Check if container has follower message content
            follower_message = self.handler.find_child_element_plus(
                container,
                'follower_message'
            )
            if not follower_message:
                return None

            message_text = follower_message.text
            # Click the message at 25% from top
            if not self.handler.click_element_at(follower_message, x_ratio=0.45, y_ratio=0.25):
                return None
            self.handler.logger.info("Clicked follower message")

            # Wait for follow status and check
            follow_status = self.handler.wait_for_element_clickable_plus('follow_status')
            if not follow_status or follow_status.text == '关注':
                self.handler.logger.info("User not followed or left, canceling")
                self.handler.press_back()
                return None

            # Get nickname from message
            nickname_element = self.handler.try_find_element_plus('souler_name')
            if not nickname_element:
                self.handler.logger.error("Failed to find nickname of message")
                self.handler.press_back()
                return None

            nickname = nickname_element.text

            # If user is followed, create user record
            self.handler.logger.info(f"User {nickname} is followed, creating user record")
            await UserDAO.get_or_create(nickname)

            await seat_manager.check.check_seats_on_entry(nickname)

            # Try to send gift first
            if self.send_gift():
                return MessageInfo(
                    content=message_text,
                    nickname=nickname,
                    avatar_element=None,
                    relation_tag=True
                )
            
            # If gift sending failed, try to greet
            if self.send_greeting():
                return MessageInfo(
                    content=message_text,
                    nickname=nickname,
                    avatar_element=None,
                    relation_tag=True
                )

            return None

        except Exception as e:
            self.handler.log_error(f"Error processing greeting: {traceback.format_exc()}")
            return None

    def send_gift(self):
        """Send soul power gift to follower"""
        try:
            # Click send gift button
            send_gift = self.handler.wait_for_element_clickable_plus('send_gift')
            if not send_gift:
                self.handler.logger.error("Failed to find send gift button")
                return False
            send_gift.click()
            self.handler.logger.info("Clicked send gift")

            # Wait for give gift button to ensure gift panel loaded
            give_gift = self.handler.wait_for_element_clickable_plus('give_gift')
            if not give_gift:
                self.handler.logger.error("Failed to find give gift button")
                self.handler.press_back()
                return False

            # Try to find and send soul power gift
            soul_power = self.handler.try_find_element_plus('soul_power', log=False)
            if soul_power and (not soul_power.text == '不增加灵魂力') and (not soul_power.text == '+12灵魂力'):
                # Click give gift button to send
                give_gift.click()
                self.handler.logger.info("Sent soul power gift")
                return True

            # If no gift available, close gift panel
            self.handler.press_back()
            return False

        except Exception as e:
            self.handler.log_error(f"Error sending gift: {traceback.format_exc()}")
            return False

    def send_greeting(self):
        """Send greeting message to follower"""
        try:
            greet_follower = self.handler.wait_for_element_clickable_plus('greet_follower')
            if not greet_follower:
                self.handler.logger.error("Failed to find greet button")
                return False

            greet_follower.click()
            self.handler.logger.info("Clicked greet button")

            # Wait and click send message button
            send_button = self.handler.wait_for_element_clickable_plus('button_send')
            if not send_button:
                self.handler.logger.error("Failed to find send message button")
                return False
            send_button.click()
            self.handler.logger.info("Sent greeting message")
            return True

        except Exception as e:
            self.handler.log_error(f"Error sending greeting: {traceback.format_exc()}")
            return False 

    async def handle_user_enter(self, username: str):
        """Handle user enter event"""
        try:
            # Check if sleep mode is enabled
            if self.sleep_manager.is_sleep_mode_enabled():
                self.handler.logger.info(f"Sleep mode is enabled, skipping greeting for {username}")
                return

            # Rest of the greeting logic...
            # ... existing code ...

        except Exception as e:
            self.handler.log_error(f"Error handling user enter: {traceback.format_exc()}") 