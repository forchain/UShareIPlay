from appium.webdriver.common.appiumby import AppiumBy
from ..utils.app_handler import AppHandler
import re

class SoulHandler(AppHandler):
    def __init__(self, driver, config):
        super().__init__(driver, config)
        self.previous_message_ids = set()  # Store previous element IDs

    def get_latest_message(self):
        """Get new message contents that weren't seen before"""
        try:
            self.switch_to_app()
            # Get elements by ID directly without replace
            message_contents = self.driver.find_elements(
                AppiumBy.ID,
                self.config['elements']['message_content']
            )
            
            # Then filter using regex and collect valid messages with their IDs
            pattern = r'souler\[.+\]说：:(.+)'
            current_messages = {}  # Dict to store element_id: message_element pairs
            
            for msg in message_contents:
                content = msg.get_attribute('content-desc')
                if content and re.match(pattern, content):
                    element_id = msg.id  # Get Appium's unique element ID
                    current_messages[element_id] = msg
            
            # Find new message IDs (not in previous set)
            current_ids = set(current_messages.keys())
            new_message_ids = current_ids - self.previous_message_ids
            
            # Update previous message IDs for next check
            self.previous_message_ids = current_ids
            
            if new_message_ids:
                # Extract content for new messages
                new_message_contents = [
                    re.match(pattern, current_messages[msg_id].get_attribute('content-desc')).group(1)
                    for msg_id in new_message_ids
                ]
                print(f"Found {len(new_message_contents)} new messages")
                print(f"New message contents: {new_message_contents}")
                return new_message_contents
            
            # print("No new messages")
            return None
            
        except Exception as e:
            print(f"Error getting message: {str(e)}")
            return None

    def send_message(self, message):
        """Send message"""
        try:
            self.switch_to_app()
            
            # Click on the input box entry first
            input_box_entry = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['input_box_entry']
            )
            input_box_entry.click()
            print("Clicked input box entry")

            # Wait 1 second for input box to be ready
            import time
            time.sleep(1)
            print("Waited 1 second for input box")

            # Now find and interact with the actual input box
            input_box = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['input_box']
            )
            input_box.send_keys(message)
            print(f"Entered message: {message}")

            # click send button
            send_button = self.driver.find_element(
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