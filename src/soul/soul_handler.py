import time
import traceback

from PIL.ImageOps import contain
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import WebDriverException

from ..utils.app_handler import AppHandler
import re
from dataclasses import dataclass
from selenium.common.exceptions import StaleElementReferenceException
from ..core.base_command import BaseCommand
from .message_manager import MessageManager

# Constants
@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    avatar_element: object  # WebElement for avatar, always exists
    relation_tag: bool = False  # True if user has relation tag


class SoulHandler(AppHandler):
    def __init__(self, driver, config, controller):
        super().__init__(driver, config, controller)
        self.message_manager = MessageManager(self)
        self.previous_message_ids = set()  # Store previous element IDs
        self.party_id = None
        self.last_content = None  # Last message content
        self.second_last_content = None  # Second last message content
    
    async def get_latest_message(self, enabled=True):
        """Get latest messages from the chat"""
        return await self.message_manager.get_latest_message(enabled)

    def send_message(self, message):
        """Send message"""
        self.switch_to_app()

        # Click on the input box entry first
        input_box_entry = self.wait_for_element_clickable_plus('input_box_entry')
        if not input_box_entry:
            self.logger.error(f'cannot find input box entry, might be in loading')
            return
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

        input_box_entry = self.try_find_element_plus('input_box_entry', log=False)
        if input_box_entry:
            self.logger.info("Found input box entry, no need to hide input dialog")
            return True

        input_box = self.wait_for_element_clickable_plus('input_box', timeout=1)
        if input_box:
            self.click_element_at(input_box, 0.5, -1)
            self.logger.info("Hide input dialog")
            # if input_box.text == '输入新消息':
            #     self.press_back()
            #     self.logger.info("Hide input dialog")
            # else:
            #     send_button = self.wait_for_element_clickable_plus('button_send')
            #     send_button.click()
            #     self.logger.warning("Failed to send message, resent ")
        else:
            self.logger.info("No input box found, no need to hide input dialog")

        input_box_entry = self.wait_for_element_clickable_plus('input_box_entry')
        if not input_box_entry:
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
        self.logger.info("Clicked search entry")

        # Find search box and input party ID
        search_box = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['search_box']
        )
        if not search_box:
            self.logger.error(f"Search box not found")
            return {
                'error': 'Failed to find search box',
            }
        search_box.send_keys(party_id)
        self.logger.info(f"Entered party ID: {party_id}")

        # Click search button
        search_button = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['search_button']
        )
        if not search_button:
            self.logger.error(f"Search button not found")
            return {
                'error': 'Failed to find search button',
            }
        search_button.click()
        self.logger.info("Clicked search button")

        party_tab = self.wait_for_element_clickable(AppiumBy.XPATH, self.config['elements']['party_tab'])
        if not party_tab:
            self.logger.error(f"Party tab not found")
            return {'error': 'Party tab not found'}
        party_tab.click()
        self.logger.info("Clicked party tab")

        search_result = self.wait_for_element(AppiumBy.ID, self.config['elements']['party_search_result'])
        if not search_result:
            self.logger.error(f"Party search result not found")
            return {'error': 'Party search result not found'}
        self.logger.info("Found party search result")

        empty_result = self.find_child_element(search_result, AppiumBy.ID,
                                               self.config['elements']['party_search_empty'])
        if empty_result:
            self.logger.error(f"Party ID: {party_id} not found")
            return {'error': 'Party not found'}

        party_entry = self.find_child_element(search_result, AppiumBy.ID, self.config['elements']['party_search_entry'])
        if not party_entry:
            self.logger.error(f"Party entry: {party_id} not found")
            return {'error': 'Party entry not found'}

        # Check party status after finding the message
        # Check if the party has ended
        party_online = self.find_child_element(party_entry, AppiumBy.ID, self.config['elements']['party_online'])
        if party_online:
            # Party is ongoing, click the party entry
            party_entry.click()
            self.logger.info("Clicked party entry")

            time.sleep(1)
            party_back = self.try_find_element(AppiumBy.ID, self.config['elements']['party_back'], log=False)
            if party_back:
                self.logger.info(f"Found back to party dialog and close")
                party_back.click()
        else:
            # Party has ended, navigate to create a new party
            self.logger.info("Party has ended, navigating to create a new party")
            self.press_back()  # Go back to the home screen

            planet_tab = self.wait_for_element_clickable(AppiumBy.ID, self.config['elements']['planet_tab'])
            if not planet_tab:
                self.logger.error("Failed to find planet tab")
                return {'error': 'Failed to find planet tab'}
            planet_tab.click()
            self.logger.info("Clicked planet tab")

            party_hall_entry = self.wait_for_element_clickable(AppiumBy.XPATH,
                                                               self.config['elements']['party_hall_entry'])
            if not party_hall_entry:
                self.logger.error(f"Party hall entry not found")
                return {'error': 'Party hall entry not found'}
            party_hall_entry.click()
            self.logger.info("Clicked party hall entry")

            create_party_entry = self.wait_for_element_clickable(AppiumBy.ID,
                                                                 self.config['elements']['create_party_entry'])
            if not create_party_entry:
                self.logger.error(f"Party creation entry not found")
                return {'error': 'Party creation entry not found'}
            create_party_entry.click()
            self.logger.info("Clicked create party entry")

            confirm_party_button = self.wait_for_element_clickable(AppiumBy.ID,
                                                                   self.config['elements'][
                                                                       'confirm_party'], timeout=5)
            if confirm_party_button:
                confirm_party_button.click()
                self.logger.info("Clicked confirm party button")
                self.wait_for_element(AppiumBy.ID, self.config['elements']['create_party_screen'])
            else:
                restore_party_button = self.wait_for_element_clickable(AppiumBy.ID, self.config['elements'][
                    'restore_party'])
                if restore_party_button:
                    restore_party_button.click()
                    self.logger.info("Clicked restore party button")
                confirm_party_button = self.wait_for_element_clickable(AppiumBy.ID,
                                                                       self.config['elements'][
                                                                           'confirm_party'], timeout=5)
                if confirm_party_button:
                    confirm_party_button.click()
                    self.logger.info("Clicked confirm party button")

            create_party_button = self.try_find_element_plus('create_party_button')
            if create_party_button:
                create_party_button.click()
                self.logger.info("Clicked create party button")


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
            self.logger.error(f"Error inviting to party: {traceback.format_exc()}")
            return {
                'error': f'Failed to invite to party to {party_id}',
                'party_id': party_id
            }

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
