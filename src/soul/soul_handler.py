from PIL.ImageOps import contain
from appium.webdriver.common.appiumby import AppiumBy
from ..utils.app_handler import AppHandler
import re
from dataclasses import dataclass

@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    avatar_element: object  # WebElement for avatar, always exists
    relation_tag: bool = False  # True if user has relation tag

class SoulHandler(AppHandler):
    def __init__(self, driver, config):
        super().__init__(driver, config)
        self.previous_message_ids = set()  # Store previous element IDs

    def get_latest_message(self, enabled = True):
        """Get new message contents that weren't seen before"""
        try:
            self.switch_to_app()

            # Get message list container
            message_list = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['message_list']
            )
            
            if not message_list:
                if enabled:
                    print("[Warning]get_latest_message cannot find message_list, may be minimized")
                    floating_entry = self.try_find_element(AppiumBy.ID, self.config['elements']['floating_entry'])
                    if floating_entry:
                        floating_entry.click()
                        message_list = self.try_find_element(
                            AppiumBy.ID,
                            self.config['elements']['message_list']
                        )
                    else:
                        print("[Warning]get_latest_message still cannot find message_list, may stay in unknown pages, go back first")
                        self.press_back()
                return None

            # Check if there is a new message tip and click it
            new_message_tip = self.try_find_element(AppiumBy.ID, self.config['elements']['new_message_tip'], log=False)
            if new_message_tip and enabled:
                print(f'Found new message tip')
                new_message_tip.click()
                print(f'Clicked new message tip')

            # Get all ViewGroup containers first
            containers = message_list.find_elements(AppiumBy.CLASS_NAME, "android.view.ViewGroup")
            print(f"Found {len(containers)} ViewGroup containers")
            
            # Process each container and collect message info
            current_messages = {}  # Dict to store element_id: MessageInfo pairs
            pattern = r'souler\[.+\]说：:(.+)'

            for container in containers:
                # Check if container has valid message content
                content_element = self.find_child_element(
                    container,
                    AppiumBy.ID,
                    self.config['elements']['message_content']
                )
                
                if content_element:
                    content = content_element.get_attribute('content-desc')
                    if content and re.match(pattern, content):
                        element_id = container.id
                        
                        # Get nickname
                        nickname_element = self.find_child_element(
                            container,
                            AppiumBy.ID,
                            self.config['elements']['sender_nickname']
                        )
                        nickname = self.get_element_text(nickname_element)
                        if not nickname:
                            continue
                        
                        # Get avatar element
                        avatar_element = self.find_child_element(
                            container,
                            AppiumBy.ID,
                            self.config['elements']['sender_avatar']
                        )
                        if not avatar_element:
                            continue
                        
                        # Check for relation tag
                        relation_element = self.find_child_element(
                            container,
                            AppiumBy.ID,
                            self.config['elements']['sender_relation']
                        )
                        if not relation_element:
                            relation_element = self.find_child_element(
                                container,
                                AppiumBy.ID,
                                self.config['elements']['sender_flag']
                            )

                        has_relation = relation_element is not None
                        
                        # Create MessageInfo object
                        message_info = MessageInfo(
                            content=re.match(pattern, content).group(1),
                            nickname=nickname,
                            avatar_element=avatar_element,
                            relation_tag=has_relation
                        )
                        
                        current_messages[element_id] = message_info

            # Find new message IDs (not in previous set)
            current_ids = set(current_messages.keys())
            new_message_ids = current_ids - self.previous_message_ids

            # Update previous message IDs for next check
            self.previous_message_ids = current_ids

            if new_message_ids:
                # Create result dict with only new messages
                new_messages = {
                    msg_id: current_messages[msg_id]
                    for msg_id in new_message_ids
                }
                print(f"Found {len(new_messages)} new messages")
                return new_messages

            return None

        except Exception as e:
            print(f"Error getting message: {str(e)}")
            return None

    def send_message(self, message):
        """Send message"""
        try:
            self.switch_to_app()

            # Click on the input box entry first
            input_box_entry = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['input_box_entry']
            )
            input_box_entry.click()
            print("Clicked input box entry")

            # # Wait 1 second for input box to be ready
            # import time
            # time.sleep(1)
            # print("Waited 1 second for input box")

            # Now find and interact with the actual input box
            input_box = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['input_box']
            )
            input_box.send_keys(message)
            print(f"Entered message: {message}")

            # click send button
            send_button = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['button_send']
            )
            send_button.click()
            print("Clicked send button")

            # hide input dialog
            self.press_back()
            print("Hide input dialog")

        except Exception as e:
            print(f"Error sending message: {str(e)}")

    def invite_user(self, message_info: MessageInfo):
        """
        Invite user to join the room
        Args:
            message_info: MessageInfo object containing user information
        Returns:
            dict: Result of invitation with user info
        """
        try:
            # Check relation tag
            if not message_info.relation_tag:
                return {
                    'error': '必须群主关注的人才能邀请群主入群'
                }

            # Click avatar to open profile
            if message_info.avatar_element:
                message_info.avatar_element.click()
                print("Clicked sender avatar")
            else:
                return {'error': 'Avatar element not found'}
            
            # Wait for profile page and click profile avatar
            profile_avatar = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['profile_avatar']
            )
            if not profile_avatar:
                return {'error': 'Failed to open profile page'}
            
            profile_avatar.click()
            print("Clicked profile avatar")

            # Find and click chat button
            chat_button = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['moments_chat']
            )
            if not chat_button:
                return {'error': 'Failed to find chat button'}
            
            chat_button.click()
            print("Clicked chat button")
            
            # Wait for chat title to appear to confirm we're in chat page
            chat_title = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['chat_title']
            )
            if not chat_title:
                return {'error': 'Failed to enter chat page'}
            print("Entered chat page")

            # Look for invite links
            invite_links = self.driver.find_elements(
                AppiumBy.ID,
                self.config['elements']['invite_link']
            )
            
            if not invite_links:
                print("Invite link not found, room may be closed")
                self.press_back()
                self.press_back()
                return {'error': 'Room is closed'}
            
            # Click the last (most recent) invite link
            last_link = invite_links[-1]
            last_link.click()
            print(f"Clicked last invite link (found {len(invite_links)} links)")

            return {'user': message_info.nickname}

        except Exception as e:
            print(f"Error inviting user: {str(e)}")
            return {'error': str(e)}
