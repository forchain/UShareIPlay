from ..managers.message_manager import MessageManager
from ..core.app_handler import AppHandler
from ..core.singleton import Singleton


class SoulHandler(AppHandler, Singleton):
    def __init__(self, driver, config, controller):
        print("SoulHandler.__init__ 开始")
        super().__init__(driver, config, controller)
        print("SoulHandler AppHandler 初始化完成")
        # 延迟初始化 message_manager，避免循环依赖
        self._message_manager = None
        self.previous_message_ids = set()  # Store previous element IDs
        self.party_id = None
        self.last_content = None  # Last message content
        self.second_last_content = None  # Second last message content
        print("SoulHandler.__init__ 完成")

    @property
    def message_manager(self):
        """延迟获取 MessageManager 实例"""
        if self._message_manager is None:
            self._message_manager = MessageManager.instance()
        return self._message_manager

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
        # self.logger.info("Clicked input box entry")

        # Now find and interact with the actual input box
        input_box = self.wait_for_element_clickable_plus('input_box')
        if not input_box:
            self.logger.error(f'cannot find input box, might be in chat screen')
            return {
                'error': 'Failed to find input box',
            }

        if len(message) > 0:
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
            # self.logger.info("Clicked send button")

        self.click_element_at(input_box, 0.5, -1)
        # self.logger.info("Hide input dialog")

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
