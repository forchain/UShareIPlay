import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.webdriver.common.appiumby import AppiumBy


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
            print(f"Found element: {locator_value}")
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
        """切换到指定应用"""
        self.driver.activate_app(self.config['package_name'])
        time.sleep(1)

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
        print('try 66')

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

    def try_find_element(self, locator_type, locator_value):
        """Try to find element and return it"""
        try:
            return self.driver.find_element(locator_type, locator_value)
        except:
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
