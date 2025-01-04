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
        self.party_id = None

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
                floating_entry = self.try_find_element(AppiumBy.ID, self.config['elements']['floating_entry'],
                                                       clickable=True)
                if floating_entry:
                    floating_entry.click()
                    message_list = self.try_find_element(
                        AppiumBy.ID,
                        self.config['elements']['message_list']
                    )
                else:
                    square_tab = self.try_find_element(AppiumBy.ID, self.config['elements']['square_tab'])
                    if square_tab:
                        print(
                            "[Warning] get_latest_message already back in home but no party entry found, try go to party")
                        square_tab.click()
                        party_home = "FM15321640"
                        party_id = self.party_id if self.party_id else party_home
                        self.find_party_to_join(party_id)
                        self.party_id = None
                    else:
                        print(
                            "[Warning] get_latest_message still cannot find message_list, may stay in unknown pages, go back first")
                        if not self.press_back():
                            print('[Error]get_latest_message Failed to press back')
                            return None

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
            self.logger.error(f'cannot find input box entry, might be in loading')
            return
        input_box_entry.click()
        self.logger.info("Clicked input box entry")

        # # Wait 1 second for input box to be ready
        # import time
        # time.sleep(1)
        # print("Waited 1 second for input box")

        # Now find and interact with the actual input box
        input_box = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['input_box']
        )
        if not input_box:
            self.logger.error(f'send_message cannot find input box, might be in chat screen')
            return
        input_box.send_keys(message)
        self.logger.info(f"Entered message: {message}")

        # click send button
        send_button = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['button_send']
        )
        send_button.click()
        self.logger.info("Clicked send button")

        input_box_entry = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['input_box_entry'], timeout=1
        )
        if not input_box_entry:
            # hide input dialog
            self.press_back()
            self.logger.info("Hide input dialog")
        else:
            self.logger.info("Found input box entry, no need to hide input dialog")

        input_box = self.try_find_element(AppiumBy.ID, self.config['elements']['input_box'], log=False)
        if input_box:
            self.press_back()
            self.logger.warning("Failed to hide input dialog, try again")

    def find_party_to_join(self, party_id):
        # Find and click search entry
        search_entry = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['search_entry']
        )
        if not search_entry:
            print(f"Search entry not found")
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
            print(f"Search box not found")
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
            print(f"Search button not found")
            return {
                'error': 'Failed to find search button',
            }
        search_button.click()
        print("Clicked search button")

        party_tab = self.wait_for_element_clickable(AppiumBy.XPATH, self.config['elements']['party_tab'])
        if not party_tab:
            print(f"Party tab not found")
            return {'error': 'Party tab not found'}
        party_tab.click()
        print("Clicked party tab")

        search_result = self.wait_for_element(AppiumBy.ID, self.config['elements']['party_search_result'])
        if not search_result:
            print(f"Party search result not found")
            return {'error': 'Party search result not found'}
        print("Found party search result")

        empty_result = self.find_child_element(search_result, AppiumBy.ID,
                                               self.config['elements']['party_search_empty'])
        if empty_result:
            print(f"Party ID: {party_id} not found")
            return {'error': 'Party not found'}

        party_entry = self.find_child_element(search_result, AppiumBy.ID, self.config['elements']['party_search_entry'])
        if not party_entry:
            print(f"Party entry: {party_id} not found")
            return {'error': 'Party entry not found'}

        # Check party status after finding the message
        # Check if the party has ended
        party_online = self.find_child_element(party_entry, AppiumBy.ID, self.config['elements']['party_online'])
        if party_online:
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
            if not planet_tab:
                print("Failed to find planet tab")
                return {'error': 'Failed to find planet tab'}
            planet_tab.click()
            print("Clicked planet tab")

            party_hall_entry = self.wait_for_element_clickable(AppiumBy.XPATH,
                                                               self.config['elements']['party_hall_entry'])
            if not party_hall_entry:
                print(f"Party hall entry not found")
                return {'error': 'Party hall entry not found'}
            party_hall_entry.click()
            print("Clicked party hall entry")

            create_party_entry = self.wait_for_element_clickable(AppiumBy.ID,
                                                                 self.config['elements']['create_party_entry'])
            if not create_party_entry:
                self.logger.error(f"Party creation entry not found")
                return {'error': 'Party creation entry not found'}
            create_party_entry.click()
            self.logger.info("Clicked create party entry")

            confirm_party_button = self.wait_for_element_clickable(AppiumBy.ID,
                                                                   self.config['elements'][
                                                                       'confirm_party'], timeout=1)
            if confirm_party_button:
                confirm_party_button.click()
                self.logger.info("Clicked confirm party button")

            self.wait_for_element(AppiumBy.ID, self.config['elements']['create_party_screen'])
            create_party_button = self.try_find_element(AppiumBy.ID,
                                                        self.config['elements']['create_party_button'])
            if create_party_button:
                create_party_button.click()
                self.logger.info("Clicked create party button")
            else:
                restore_party_button = self.wait_for_element_clickable(AppiumBy.ID, self.config['elements'][
                    'restore_party'])
                if restore_party_button:
                    restore_party_button.click()
                    self.logger.info("Clicked restore party button")

        input_box_entry = self.wait_for_element(AppiumBy.ID, self.config['elements']['input_box_entry'])
        if not input_box_entry:
            self.logger.error(f"Input box entry not found")
            return {'error': 'Input box entry not found'}
        self.logger.info(f"Entered party {party_id}")

        claim_reward = self.try_find_element(AppiumBy.ID, self.config['elements']['claim_reward'])
        if claim_reward:
            claim_reward.click()
            self.logger.info("Claimed party creation reward")

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

            self.wait_for_element(AppiumBy.ID, self.config['elements']['more_menu_container'])

            end_party = self.try_find_element(
                AppiumBy.XPATH,
                self.config['elements']['end_party']
            )

            if end_party:
                end_party.click()
                confirm_end = self.wait_for_element_clickable(AppiumBy.XPATH, self.config['elements']['confirm_end'])
                confirm_end.click()
                self.party_id = party_id
                return {'party_id': party_id, 'user': message_info.nickname}

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
        # Check relation tag
        if not message_info.relation_tag:
            return {
                'error': 'Only friends of owner can apply administrators',
            }

        # Click avatar to open profile
        avatar = message_info.avatar_element
        if avatar:
            try:
                avatar.click()
                self.logger.info("Clicked sender avatar")
            except StaleElementReferenceException as e:
                self.logger.error('Avatar element is unavailable')
                return {
                    'error': 'Avatar element is unavailable',
                }
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
            action = "Invite"
        else:
            confirm_button = self.wait_for_element_clickable(
                AppiumBy.XPATH,
                self.config['elements']['confirm_dismiss']
            )
            action = "Dismiss"

        if not confirm_button:
            return {'error': f'Failed to find {action} confirmation button'}

        confirm_button.click()
        print(f"Clicked {action} confirmation button")

        return {'user': message_info.nickname,
                'action': action}

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
