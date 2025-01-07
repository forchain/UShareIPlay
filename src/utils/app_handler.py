import time
import traceback

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.remote.webelement import WebElement
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException, TimeoutException
import selenium
import logging
import os
from datetime import datetime


class AppHandler:
    def __init__(self, driver, config):
        self.driver = driver
        self.config = config
        self.logger = self._setup_logger()
        self.error_count = 0

    def _setup_logger(self):
        """Setup logger for the handler
        Returns:
            logging.Logger: Configured logger instance
        """
        # Create logs directory if it doesn't exist
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        # Get current date for log file name
        current_date = datetime.now().strftime('%Y-%m-%d')
        log_file = f'logs/{self.__class__.__name__}_{current_date}.log'
        
        # Create logger
        logger = logging.getLogger(self.__class__.__name__)
        logger.setLevel(logging.DEBUG)
        
        # Create file handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        
        # Create formatter
        formatter = logging.Formatter(
            '[%(levelname)s]%(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Add handlers to logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger

    def log_info(self, message):
        """Log info level message"""
        self.logger.info(message)

    def log_error(self, message):
        """Log error level message"""
        self.logger.error(message)

    def log_debug(self, message):
        """Log debug level message"""
        self.logger.debug(message)

    def log_warning(self, message):
        """Log warning level message"""
        self.logger.warning(message)

    def wait_for_element(self, locator_type, locator_value, timeout=10):
        """Wait for element to be present and return it"""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((locator_type, locator_value))
            )
            self.log_debug(f"Found element: {locator_value}")
            return element
        except Exception as e:
            self.logger.warning(f"Element not found within {timeout} seconds: {locator_value}")
            self.logger.warning(f"Error: {str(e)}")
            return None

    def is_element_clickable(self, element):
        """Check if element is clickable
        Args:
            element: WebElement to check
        Returns:
            bool: True if element is clickable, False otherwise
        """
        try:
            if not element:
                return False
            
            # First check if element exists and is displayed
            if not element.is_displayed():
                return False
            
            # Then check if element is enabled
            if not element.is_enabled():
                return False
            
            # Finally check clickable attribute
            clickable = element.get_attribute("clickable")
            return clickable == "true"
        
        except Exception as e:
            self.logger.warning(f"Error checking if element is clickable: {str(e)}")
            return False

    def wait_for_element_clickable_plus(self, element_key: str, timeout: int = 10) -> WebElement:
        """Enhanced wait_for_element using just element key"""
        try:
            locator_type, value = self._get_locator(element_key)
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((locator_type, value))
            )
            self.logger.debug(f"Found clickable element: {element_key}")
            return element
        except TimeoutException as e:
            self.logger.warning(f"Clickable element {element_key}:{value} not found within {timeout} seconds ")
            return None
        except WebDriverException as e:
            self.logger.error(f"Trace: {traceback.format_exc()}")
            self.logger.error(f"Error: {str(e)}")
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
            self.logger.debug(f"Found clickable element: {locator_value}")
            return element
        except TimeoutException as e:
            self.logger.warning(f"Clickable element not found within {timeout} seconds: {locator_value}")
            return None
        except WebDriverException as e:
            self.logger.error(f"Trace: {traceback.format_exc()}")
            self.logger.error(f"Error: {str(e)}")
            return None

    def switch_to_app(self):
        """Switch to specified app"""
        try:
            self.driver.activate_app(self.config['package_name'])
        except selenium.common.exceptions.WebDriverException as e:
            self.logger.error(f"Failed to switch to app")
            return False
        reminder_ok = self.try_find_element(AppiumBy.ID, self.config['elements']['reminder_ok'], log=False)
        if reminder_ok:
            self.logger.debug(f"Found reminder dialog and close")
            reminder_ok.click()
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
        self.logger.debug('Pressed Return Key')

    def press_back(self):
        """Press Android back button"""
        try:
            self.driver.press_keycode(4)  # Android back key code
        except WebDriverException as e:
            self.error_count += 1
            self.logger.error(f"Failed to press back button,  times: {self.error_count}, trace:{traceback.format_exc()} error: {str(e)}")
            return False

        self.error_count = 0
        self.logger.debug("Pressed back button")
        return True

    def press_dpad_down(self):
        """Press Android DPAD down button"""
        self.driver.press_keycode(20)  # KEYCODE_DPAD_DOWN
        self.logger.debug("Pressed DPAD down button")

    def press_volume_up(self):
        """Press Android volume up button"""
        self.driver.press_keycode(24)  # KEYCODE_VOLUME_UP
        self.logger.debug("Pressed volume up button")

    def press_volume_down(self):
        """Press Android volume down button"""
        self.driver.press_keycode(25)  # KEYCODE_VOLUME_DOWN
        self.logger.debug("Pressed volume down button")

    def press_right_key(self, times=1):
        """Simulate pressing the right key multiple times
        Args:
            times: int, number of times to press the right key
        """
        for _ in range(times):
            self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'input keyevent KEYCODE_DPAD_RIGHT'
                }
            )
            time.sleep(0.1)  # Small delay between key presses

    def try_find_element_plus(self, element_key: str, log=True, clickable=False) -> WebElement:
        """Enhanced try_find_element using just element key"""
        try:
            locator_type, value = self._get_locator(element_key)
            element = self.driver.find_element(locator_type, value)
            if clickable:
                element = self.wait_for_element_clickable_plus(element_key)
            return element
        except Exception as e:
            if log:
                self.logger.warning(f"Failed to find element '{element_key}' with value '{value}'")
            return None

    def try_find_element(self, locator_type, locator_value, log=True, clickable=False):
        """Try to find element and return it"""
        try:
            element = self.driver.find_element(locator_type, locator_value)
            if element and clickable:
                element = self.wait_for_element_clickable(locator_type, locator_value)
            return element
        except:
            if log: 
                self.logger.warning(f"Element not found: {locator_value}")
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
                    self.logger.debug(f"Found element after polling: {locator_value}")
                    return element
            except Exception:
                pass
            time.sleep(poll_frequency)
            self.logger.debug(f"Polling for element: {locator_value}")
        self.logger.warning(f"Element not found after polling for {timeout} seconds: {locator_value}")
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
                    self.logger.debug(f"Found clickable element after polling: {locator_value}")
                    return element
            except Exception:
                pass
            time.sleep(poll_frequency)
            self.logger.debug(f"Polling for clickable element: {locator_value}")
        self.logger.warning(f"Clickable element not found after polling for {timeout} seconds: {locator_value}")
        return None

    def set_clipboard_text(self, text):
        """Set clipboard text using Appium's native method
        Args:
            text: str, text to be copied to clipboard
        """
        self.driver.set_clipboard_text(text)
        self.logger.debug(f"Copied '{text}' to clipboard")

    def paste_text(self):
        """Execute paste operation using Android keycode"""
        self.driver.press_keycode(279)  # KEYCODE_PASTE = 279
        self.logger.debug("Pressed paste key")

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
            self.logger.warning(f"Error getting element text: {str(e)}")
            return ""

    def try_get_attribute(self, element, attribute):
        """Try to get an attribute from a web element, catching StaleElementReferenceException."""
        try:
            return element.get_attribute(attribute)
        except StaleElementReferenceException:
            self.logger.warning(f"Unable to get  attribute {attribute}: Element is no longer attached to the DOM.")
            return None

    def _get_locator(self, element_key: str) -> tuple:
        """Helper to get locator type and value from element key"""
        if element_key not in self.config['elements']:
            raise ValueError(f"Element key '{element_key}' not found in config")
        
        value = self.config['elements'][element_key]
        locator_type = AppiumBy.XPATH if value.startswith('//') else AppiumBy.ID
        return locator_type, value


    def find_elements_plus(self, element_key: str) -> list:
        """Enhanced find_elements using just element key"""
        try:
            locator_type, value = self._get_locator(element_key)
            return self.driver.find_elements(locator_type, value)
        except Exception as e:
            print(f"Failed to find elements '{element_key}' with value '{value}': {str(e)}")
            return []
