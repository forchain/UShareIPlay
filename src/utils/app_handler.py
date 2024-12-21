import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import StaleElementReferenceException
import selenium


class AppHandler:
    def __init__(self, driver, config):
        self.driver = driver
        self.config = config

    def wait_for_element(self, locator_type, locator_value, timeout=10):
        """
        Wait for element to be present and return it
        Args:
            locator_type: AppiumBy.ID or AppiumBy.XPATH etc.
            locator_value: The locator value
            timeout: Maximum time to wait in seconds
        Returns:
            WebElement if found, None if not found
        """
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((locator_type, locator_value))
            )
            # print(f"Found element: {locator_value}")
            return element
        except Exception as e:
            print(f"Element not found within {timeout} seconds: {locator_value}")
            print(f"Error: {str(e)}")
            return None

    def wait_for_element_clickable(self, locator_type, locator_value, timeout=10):
        """
        Wait for element to be clickable and return it
        Args:
            locator_type: AppiumBy.ID or AppiumBy.XPATH etc.
            locator_value: The locator value
            timeout: Maximum time to wait in seconds
        Returns:
            WebElement if found and clickable, None if not
        """
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((locator_type, locator_value))
            )
            print(f"Found clickable element: {locator_value}")
            return element
        except Exception as e:
            print(f"Clickable element not found within {timeout} seconds: {locator_value}")
            print(f"Error: {str(e)}")
            return None

    def switch_to_app(self):
        """
        Switch to specified app
        Returns:
            bool: True if successful, False if failed
        """
        try:
            self.driver.activate_app(self.config['package_name'])
        except selenium.common.exceptions.WebDriverException as e:
            if "error: closed" in str(e):
                print(f"Failed to switch to app: connection closed")
                return False
            raise e
        reminder_ok = self.try_find_element(AppiumBy.ID, self.config['elements']['reminder_ok'], log=False)
        if reminder_ok:
            print(f"Found reminder dialog and close")
            reminder_ok.click()
        element = self.wait_for_element(AppiumBy.ID, self.config['elements']['content_container'], timeout=10)
        if not element:
            print(f"Failed to switch to app: content_container not found")
            return False            
        time.sleep(0.1)
        return True

    def close_app(self):
        """关闭应用"""
        self.driver.terminate_app(self.config['package_name'])
    
    def switch_to_activity(self, activity):
        """Switch to the specified activity"""
        package_name = self.config['package_name']
        command = f'am start -n {package_name}/{activity}'
        self.driver.execute_script('mobile: shell', {'command': command})

    def press_enter(self, element):
        """
        Press Enter key on the given element
        Args:
            element: The WebElement to send Enter key to
        """
        self.driver.press_keycode(66)
        print('Pressed Return Key')

    def press_back(self):
        """Press Android back button"""
        self.driver.press_keycode(4)  # Android back key code
        print("Pressed back button")

    def press_dpad_down(self):
        """Press Android DPAD down button"""
        self.driver.press_keycode(20)  # KEYCODE_DPAD_DOWN
        print("Pressed DPAD down button")

    def press_volume_up(self):
        """Press Android volume up button"""
        self.driver.press_keycode(24)  # KEYCODE_VOLUME_UP
        print("Pressed volume up button")

    def press_volume_down(self):
        """Press Android volume down button"""
        self.driver.press_keycode(25)  # KEYCODE_VOLUME_DOWN
        print("Pressed volume down button")

    def try_find_element(self, locator_type, locator_value, log=True, clickable=False):
        """Try to find element and return it"""
        try:
            element = self.driver.find_element(locator_type, locator_value)
            if element and clickable:
                element = self.wait_for_element_clickable(locator_type, locator_value)
            return element
        except:
            if log: 
                print(f"Element not found: {locator_value}")
            return None

    def wait_for_element_polling(self, locator_type, locator_value, timeout=10, poll_frequency=0.5):
        """
        Wait for element using polling strategy
        Args:
            locator_type: AppiumBy.ID or AppiumBy.XPATH etc.
            locator_value: The locator value
            timeout: Maximum time to wait in seconds
            poll_frequency: How often to poll for the element
        Returns:
            WebElement if found, None if not found
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                element = self.driver.find_element(locator_type, locator_value)
                if element and element.is_displayed():
                    print(f"Found element after polling: {locator_value}")
                    return element
            except Exception:
                pass
            time.sleep(poll_frequency)
            print(f"Polling for element: {locator_value}")
        print(f"Element not found after polling for {timeout} seconds: {locator_value}")
        return None

    def wait_for_element_clickable_polling(self, locator_type, locator_value, timeout=10, poll_frequency=0.5):
        """
        Wait for element to be clickable using polling strategy
        Args:
            locator_type: AppiumBy.ID or AppiumBy.XPATH etc.
            locator_value: The locator value
            timeout: Maximum time to wait in seconds
            poll_frequency: How often to poll for the element
        Returns:
            WebElement if found and clickable, None if not
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                element = self.driver.find_element(locator_type, locator_value)
                if element and element.is_displayed() and element.is_enabled():
                    print(f"Found clickable element after polling: {locator_value}")
                    return element
            except Exception:
                pass
            time.sleep(poll_frequency)
            print(f"Polling for clickable element: {locator_value}")
        print(f"Clickable element not found after polling for {timeout} seconds: {locator_value}")
        return None

    def set_clipboard_text(self, text):
        """Set clipboard text using Appium's native method
        Args:
            text: str, text to be copied to clipboard
        """
        self.driver.set_clipboard_text(text)
        print(f"Copied '{text}' to clipboard")

    def paste_text(self):
        """Execute paste operation using Android keycode"""
        self.driver.press_keycode(279)  # KEYCODE_PASTE = 279
        print("Pressed paste key")

    def find_child_element(self, parent, locator_type, locator_value):
        """Find child element of parent element
        Args:
            parent: WebElement, parent element
            locator_type: AppiumBy.ID or AppiumBy.XPATH etc.
            locator_value: The locator value
        Returns:
            WebElement if found, None if not found
        """
        try:
            return parent.find_element(locator_type, locator_value)
        except Exception as e:
            # print(f"Child element not found: {locator_value}")
            # print(f"Error: {str(e)}")
            return None

    def find_child_elements(self, parent, locator_type, locator_value):
        """Find child elements of parent element
        Args:
            parent: WebElement, parent element
            locator_type: AppiumBy.ID or AppiumBy.XPATH etc.
            locator_value: The locator value
        Returns:
            List of WebElements if found, empty list if not found
        """
        try:
            return parent.find_elements(locator_type, locator_value)
        except Exception as e:
            # print(f"Child elements not found: {locator_value}")
            # print(f"Error: {str(e)}")
            return []

    def get_element_text(self, element):
        """Get element text safely
        Args:
            element: WebElement
        Returns:
            str: element text or empty string if element is None
        """
        try:
            return element.text if element else ""
        except Exception as e:
            print(f"Error getting element text: {str(e)}")
            return ""

    def try_get_attribute(self, element, attribute):
        """Try to get an attribute from a web element, catching StaleElementReferenceException."""
        try:
            return element.get_attribute(attribute)
        except StaleElementReferenceException:
            print(f"Unable to get  attribute {attribute}: Element is no longer attached to the DOM.")
            return None
