import time
import traceback
from dataclasses import dataclass

from appium.webdriver.common.appiumby import AppiumBy

from .message_manager import MessageManager
from ..core.app_handler import AppHandler
from ..core.singleton import Singleton


# Constants
@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    avatar_element: object  # WebElement for avatar, always exists
    relation_tag: bool = False  # True if user has relation tag


class SoulHandler(AppHandler, Singleton):
    def __init__(self, driver, config, controller):
        super().__init__(driver, config, controller)
        self.message_manager = MessageManager(self)
        self.previous_message_ids = set()  # Store previous element IDs
        self.party_id = None
        self.last_content = None  # Last message content
        self.second_last_content = None  # Second last message content

    def send_message(self, message):
        """Send message"""
        self.switch_to_app()

        # Click on the input box entry first
        input_box_entry = self.wait_for_element_clickable_plus('input_box_entry')
        if not input_box_entry:
            self.logger.error(f'cannot find input box entry, might be in loading')
            return {'error': 'cannot find input box entry, might be in loading'}
        go_back = self.try_find_element_plus('go_back_1', log=False)
        if go_back:
            go_back.click()
            self.logger.error("Clicked go back button, might be in chat screen")
            return {'error': 'cannot find input box entry, might be in chat screen'}
        input_box_entry.click()
        self.logger.info("Clicked input box entry")

        # Now find and interact with the actual input box
        input_box = self.wait_for_element_clickable_plus('input_box')
        if not input_box:
            self.logger.error(f'cannot find input box, might be in chat screen')
            return {
                'error': 'Failed to find input box',
            }
        input_box.send_keys(message)
        self.logger.info(f"Entered message: {message}")

        # click send button
        send_button = self.wait_for_element_clickable_plus('button_send')
        if not send_button:
            self.logger.error(f'cannot find send button')
            return {
                'error': 'Failed to find send button',
            }

        send_button.click()
        self.logger.info("Clicked send button")

        self.click_element_at(input_box, 0.5, -1)
        self.logger.info("Hide input dialog")

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
            self.logger.error(f"Error inviting to party: {traceback.format_exc()}")
            return {
                'error': f'Failed to invite to party to {party_id}',
                'party_id': party_id
            }

    def grab_mic_and_confirm(self):
        """Wait for the grab mic button and confirm the action"""
        try:
            # Wait for the grab mic button to be clickable
            grab_mic_button = self.wait_for_element_clickable_plus('grab_mic')
            grab_mic_button.click()

            # Wait for the confirmation dialog to appear
            confirm_button = self.wait_for_element_clickable_plus('confirm_mic')
            confirm_button.click()

        except Exception as e:
            print(f"Error grabbing mic: {str(e)}")

    def ensure_mic_active(self):
        """Ensure the microphone is active"""
        try:
            # Check if the grab mic button is present
            grab_mic_button = self.try_find_element_plus('grab_mic', log=False)

            if grab_mic_button:
                self.logger.info("Grab mic button found, grabbing mic...")
                self.grab_mic_and_confirm()
            else:
                self.logger.info("Already on mic, checking toggle mic status...")
                # Check the toggle mic button
                toggle_mic_button = self.wait_for_element_clickable_plus('toggle_mic')

                if not toggle_mic_button:
                    self.logger.error("Toggle mic button not found")
                    return

                desc = self.try_get_attribute(toggle_mic_button, 'content-desc')
                if desc == "开麦按钮":  # If we see "开麦按钮", mic is currently off
                    self.logger.info("Mic is off, turning it on...")
                    toggle_mic_button.click()
                    self.logger.info("Clicked toggle mic button to turn on mic")

        except Exception as e:
            self.logger.error(f"Error ensuring mic is active: {str(e)}")
