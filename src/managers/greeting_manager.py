import re
import traceback
from dataclasses import dataclass

from .seat_manager import seat_manager
from ..core.singleton import Singleton
from ..dal import UserDAO


@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    avatar_element: object  # WebElement for avatar, always exists
    relation_tag: bool = False  # True if user has relation tag


class GreetingManager(Singleton):
    def __init__(self):
        """Initialize GreetingManager with handler"""
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self.last_follower_message_id = None  # 记录上一条 follower message 的 element id

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    async def process_container_greeting(self, container):
        """Process greeting for follower entering room"""
        try:
            # Check if container has follower message content
            follower_message = self.handler.find_child_element_plus(
                container,
                'follower_message'
            )
            if not follower_message:
                return None

            # 获取当前 follower message 的 element id
            current_message_id = follower_message.id

            # 如果当前消息的 element id 与上一条相同，则跳过
            if current_message_id == self.last_follower_message_id:
                # self.handler.logger.info("跳过重复的 follower message")
                return None

            # 记录当前消息的 element id
            self.last_follower_message_id = current_message_id

            message_text = follower_message.text
            # Click the message at 25% from top
            x_ratio = 0.45 if message_text.startswith('你关注的') else 0.75
            if not self.handler.click_element_at(follower_message, x_ratio=x_ratio, y_ratio=0.25):
                return None
            self.handler.logger.info("Clicked follower message")

            # Wait for follow status and check
            follow_status = self.handler.wait_for_element_clickable_plus('follow_status')
            if not follow_status or follow_status.text == '关注':
                self.handler.logger.info("User not followed or left, canceling")
                self.handler.press_back()
                return None

            # Get nickname from message
            nickname_element = self.handler.try_find_element_plus('souler_name', log=False)
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
            if await self.send_greeting():
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

            # bag_tab = self.handler.wait_for_element_clickable_plus('bag_tab')
            # bag_tab.click()
            # self.handler.logger.info("Clicked bag tab")

            # Wait for give gift button to ensure gift panel loaded
            key, element = self.handler.wait_for_any_element_plus(['give_gift', 'use_item'])
            if key == 'use_pack' or not key:
                self.handler.logger.error("Failed to find give gift button")
                bottom_drawer = self.handler.try_find_element_plus('bottom_drawer', log=False)
                if bottom_drawer:
                    self.handler.click_element_at(bottom_drawer, x_ratio=0.5, y_ratio=-0.01)
                    self.handler.logger.info(f'Hid gift panel')
                return False
            give_gift = element

            # Try to find and send soul power gift
            soul_power = self.handler.try_find_element_plus('soul_power', log=False)
            if soul_power and (not (soul_power_text := soul_power.text) == '不增加灵魂力'):
                match = re.match(r'^\+(\d+)灵魂力$', soul_power_text)
                if match and (value := int(match.group(1))) < 10:
                    # Click give gift button to send
                    give_gift.click()
                    self.handler.logger.info(f"Sent soul power +{value} gift")
                    return True

            # If no gift available, close gift panel
            self.handler.press_back()
            return False

        except Exception as e:
            self.handler.log_error(f"Error sending gift: {traceback.format_exc()}")
            return False

    async def send_greeting(self):
        """Send greeting message to follower (async to prevent blocking)"""
        import asyncio
        import concurrent.futures

        try:
            # 在线程池中执行UI操作，避免阻塞事件循环
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await asyncio.wait_for(
                    loop.run_in_executor(executor, self._send_greeting_sync),
                    timeout=5.0
                )
                return result
        except asyncio.TimeoutError:
            self.handler.logger.warning("Greeting operation timed out after 5 seconds")
            return False
        except Exception as e:
            self.handler.log_error(f"Error sending greeting: {traceback.format_exc()}")
            return False

    def _send_greeting_sync(self):
        """Synchronous greeting operation"""
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
            self.handler.log_error(f"Error in sync greeting operation: {traceback.format_exc()}")
            return False
