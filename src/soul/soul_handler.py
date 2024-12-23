import time

from PIL.ImageOps import contain
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import WebDriverException

from ..utils.app_handler import AppHandler
import re
from dataclasses import dataclass
from selenium.common.exceptions import StaleElementReferenceException



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

    def get_latest_message(self, enabled=True):
        """Get new message contents that weren't seen before"""
        if not self.switch_to_app():
            print("Failed to switch to Soul app")
            return None

        # Get message list container
        message_list = self.try_find_element(
            AppiumBy.ID,
            self.config['elements']['message_list']
        )

        if not message_list:
            if enabled:
                print("[Warning] get_latest_message cannot find message_list, may be minimized")
                enable_floating_entry = True
                floating_entry = self.try_find_element(AppiumBy.ID, self.config['elements']['floating_entry'])
                if enable_floating_entry and floating_entry:
                    floating_entry.click()
                    message_list = self.try_find_element(
                        AppiumBy.ID,
                        self.config['elements']['message_list']
                    )
                else:
                    square_tab = self.try_find_element(AppiumBy.ID, self.config['elements']['square_tab'])
                    if square_tab:
                        print("[Warning] get_latest_message already back in home but no party entry found, try go to party")
                        square_tab.click()
                        self.find_party_to_join("FM15321640")
                    else:
                        print("[Warning] get_latest_message still cannot find message_list, may stay in unknown pages, go back first")
                        self.press_back()

            return None

        # Check if there is a new message tip and click it
        new_message_tip = self.try_find_element(AppiumBy.ID, self.config['elements']['new_message_tip'], log=False)
        if new_message_tip and enabled:
            print(f'Found new message tip')
            new_message_tip.click()
            print(f'Clicked new message tip')

        expand_seats = self.try_find_element(AppiumBy.ID, self.config['elements']['expand_seats'], log=False)
        if expand_seats and expand_seats.text == '收起座位':
            expand_seats.click()
            print(f'Collapsed seats')

        # Get all ViewGroup containers first
        try:
            containers = message_list.find_elements(AppiumBy.CLASS_NAME, "android.view.ViewGroup")
        except WebDriverException as e:
            print(f'[get_latest_message] cannot find message_list element, might be in loading')
            time.sleep(1)
            return None


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
                content = self.try_get_attribute(content_element, 'content-desc')
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

    def send_message(self, message):
        """Send message"""
        self.switch_to_app()

        # Click on the input box entry first
        input_box_entry = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['input_box_entry']
        )
        if not input_box_entry:
            print(f'[send_message] cannot find input box entry, might be in loading')
            return
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

        input_box = self.try_find_element(AppiumBy.ID, self.config['elements']['input_box'], log=False)
        if input_box:
            self.press_back()
            print("Failed to hide input dialog, try again")

    def find_party_to_join(self, party_id):
        # Find and click search entry
        search_entry = self.wait_for_element_clickable(
            AppiumBy.ID, 
            self.config['elements']['search_entry']
        )
        if not search_entry:
            return {
                'error': 'Failed to find search entry',
            }


        search_entry.click()
        print("Clicked search entry")

        # Find search box and input party ID
        search_box = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['search_box']
        )
        if not search_box:
            return {
                'error': 'Failed to find search box',
            }

        search_box.send_keys(party_id)
        print(f"Entered party ID: {party_id}")

        # Click search button
        search_button = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['search_button']
        )
        if not search_button:
            return {
                'error': 'Failed to find search button',
            }

        search_button.click()
        print("Clicked search button")

        party_tab = self.wait_for_element_clickable(AppiumBy.XPATH, self.config['elements']['party_tab'])
        party_tab.click()
        search_result = self.wait_for_element(AppiumBy.ID, self.config['elements']['party_search_result'])
        empty_result = self.find_child_element(search_result, AppiumBy.ID, self.config['elements']['party_search_empty'])
        if empty_result:
            print(f"Party ID: {party_id} not found")
            return {'error': 'Party not found'}
        party_entry = self.find_child_element(search_result, AppiumBy.ID, self.config['elements']['party_search_entry'])
        if not party_entry:
            print(f"Party entry: {party_id} not found")
            return {'error': 'Party entry not found'}

        # Check party status after finding the message
        # Check if the party has ended
        party_ended = self.find_child_element(party_entry, AppiumBy.ID, self.config['elements']['party_ended'])
        if not party_ended:
            # Party is ongoing, click the party entry
            party_entry.click()
            print("Clicked party entry")

            time.sleep(1)
            party_back = self.try_find_element(AppiumBy.ID, self.config['elements']['party_back'], log=False)
            if party_back:
                print(f"Found back to party dialog and close")
                party_back.click()
        else:
            # Party has ended, navigate to create a new party
            print("Party has ended, navigating to create a new party")
            self.press_back()  # Go back to the home screen
            planet_tab = self.wait_for_element_clickable(AppiumBy.ID, self.config['elements']['planet_tab'])
            if planet_tab:
                planet_tab.click()
                print("Clicked planet tab")
                party_hall_entry = self.wait_for_element_clickable(AppiumBy.XPATH,
                                                                   self.config['elements']['party_hall_entry'])
                if party_hall_entry:
                    party_hall_entry.click()
                    print("Clicked party hall entry")
                    create_party_button = self.wait_for_element_clickable(AppiumBy.ID,
                                                                          self.config['elements']['create_party'])
                    if create_party_button:
                        create_party_button.click()
                        print("Clicked create party button")
                        restore_party_button = self.wait_for_element_clickable(AppiumBy.ID, self.config['elements'][
                            'restore_party'])
                        if restore_party_button:
                            restore_party_button.click()
                            print("Clicked restore party button")
                            confirm_party_button = self.wait_for_element_clickable(AppiumBy.ID,
                                                                                   self.config['elements'][
                                                                                       'confirm_party'])
                            if confirm_party_button:
                                confirm_party_button.click()
                                print("Clicked confirm party button")


    def invite_user(self, message_info: MessageInfo, party_id: str):
        """
        Invite user to join the party
        Args:
            message_info: MessageInfo object containing user information
            party_id: str, party ID to join
        Returns:
            dict: Result of invitation
        """
        try:
            # Check relation tag
            if not message_info.relation_tag:
                return {
                    'error': '必须群主关注的人才能邀请群主入群',
                    'party_id': party_id
                }

            # Click more menu button
            more_menu = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['more_menu']
            )
            if not more_menu:
                return {
                    'error': 'Failed to find more menu button',
                    'party_id': party_id
                }

            more_menu.click()
            print("Clicked more menu button")

            # Find and click party hall entry
            party_hall = self.wait_for_element_clickable(
                AppiumBy.XPATH,
                self.config['elements']['party_hall']
            )
            if not party_hall:
                return {
                    'error': 'Failed to find party hall entry',
                    'party_id': party_id
                }

            party_hall.click()
            print("Clicked party hall entry")

            # Find and click search entry
            search_entry = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['search_entry']
            )
            if not search_entry:
                return {
                    'error': 'Failed to find search entry',
                    'party_id': party_id
                }

            search_entry.click()
            print("Clicked search entry")

            # Find search box and input party ID
            search_box = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['search_box']
            )
            if not search_box:
                return {
                    'error': 'Failed to find search box',
                    'party_id': party_id
                }

            search_box.send_keys(party_id)
            print(f"Entered party ID: {party_id}")

            # Click search button
            search_button = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['search_button']
            )
            if not search_button:
                return {
                    'error': 'Failed to find search button',
                    'party_id': party_id
                }

            search_button.click()
            print("Clicked search button")

            # Find parties search result
            parties_search = self.wait_for_element(
                AppiumBy.ID,
                self.config['elements']['parties_search']
            )
            if not parties_search:
                return {
                    'error': 'Failed to find parties search',
                    'party_id': party_id
                }

            print("Found parties search result")

            # waif for results to appear
            time.sleep(1)
            # Look for party ID element
            party_element = self.find_child_element(
                parties_search,
                AppiumBy.ID,
                self.config['elements']['party_id']
            )

            if not party_element:
                print("Party not found, returning to previous party")
                floating_entry = self.wait_for_element_clickable(
                    AppiumBy.ID,
                    self.config['elements']['floating_entry']
                )
                floating_entry.click()
                return {
                    'error': f'Party {party_id} not found',
                    'party_id': party_id
                }

            # Click party to enter
            party_element.click()
            print(f"Entered party {party_id}")

            # Grab mic and confirm
            self.grab_mic_and_confirm()

            return {'party_id': party_id, 'user': message_info.nickname}

        except Exception as e:
            print(f"Error inviting to party: {str(e)}")
            return {
                'error': str(e),
                'party_id': party_id
            }

    def manage_admin(self, message_info: MessageInfo, enable: bool):
        """
        Manage administrator status
        Args:
            message_info: MessageInfo object containing user information
            enable: bool, True to enable admin, False to disable
        Returns:
            dict: Result of operation with user info
        """
        try:
            # Check relation tag
            if not message_info.relation_tag:
                return {
                    'error': '只有群主密友才能申请管理'
                }

            # Click avatar to open profile
            if message_info.avatar_element:
                message_info.avatar_element.click()
                print("Clicked sender avatar")
            else:
                return {'error': 'Avatar element not found'}

            # Find manager invite button
            manager_invite = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['manager_invite']
            )
            if not manager_invite:
                return {'error': 'Failed to find manager invite button'}

            # Check current status
            current_text = manager_invite.text
            if enable:
                if current_text == "解除管理":
                    self.press_back()
                    return {'error': '你已经是管理员了'}
            else:
                if current_text == "管理邀请":
                    self.press_back()
                    return {'error': '你还不是管理员'}

            # Click manager invite button
            manager_invite.click()
            print("Clicked manager invite button")

            # Click confirm button
            if enable:
                confirm_button = self.wait_for_element_clickable(
                    AppiumBy.ID,
                    self.config['elements']['confirm_invite']
                )
                action = "邀请"
            else:
                confirm_button = self.wait_for_element_clickable(
                    AppiumBy.XPATH,
                    self.config['elements']['confirm_dismiss']
                )
                action = "解除"

            if not confirm_button:
                return {'error': f'Failed to find {action}确认按钮'}

            confirm_button.click()
            print(f"Clicked {action}确认按钮")

            return {'user': message_info.nickname}

        except Exception as e:
            print(f"Error managing admin: {str(e)}")
            return {'error': str(e)}

    def grab_mic_and_confirm(self):
        """Wait for the grab mic button and confirm the action"""
        try:
            # Wait for the grab mic button to be clickable
            grab_mic_button = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['grab_mic']
            )
            grab_mic_button.click()
            print("Clicked grab mic button")

            # Wait for the confirmation dialog to appear
            confirm_button = self.wait_for_element_clickable(
                AppiumBy.XPATH,
                self.config['elements']['confirm_mic']
            )
            confirm_button.click()
            print("Clicked confirm button for mic")

        except Exception as e:
            print(f"Error grabbing mic: {str(e)}")

    def ensure_mic_active(self):
        """Ensure the microphone is active"""
        try:
            # Check if the grab mic button is present
            grab_mic_button = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['grab_mic']
            )

            if grab_mic_button:
                print("Grab mic button found, grabbing mic...")
                self.grab_mic_and_confirm()
            else:
                print("Already on mic, checking toggle mic status...")
                # Check the toggle mic button
                toggle_mic_button = self.wait_for_element_clickable(
                    AppiumBy.ID,
                    self.config['elements']['toggle_mic']
                )

                if toggle_mic_button.text == "闭麦中":  # Assuming this means "Mic is off"
                    print("Mic is off, turning it on...")
                    toggle_mic_button.click()
                    print("Clicked toggle mic button to turn on mic")

        except Exception as e:
            print(f"Error ensuring mic is active: {str(e)}")
