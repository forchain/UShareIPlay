import logging
import os
import time
import traceback
from datetime import datetime
from typing import Optional, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class AppHandler:
    def __init__(self, driver, config, controller):
        print(f"AppHandler.__init__ 开始: {self.__class__.__name__}")
        self.driver = driver
        self.config = config
        print(f"AppHandler 设置 logger: {self.__class__.__name__}")
        self.logger = self._setup_logger()
        print(f"AppHandler logger 设置完成: {self.__class__.__name__}")
        self.error_count = 0
        self.controller = controller
        print(f"AppHandler.__init__ 完成: {self.__class__.__name__}")

    def _setup_logger(self):
        """Setup logger for the handler
        Returns:
            logging.Logger: Configured logger instance
        """
        print(f"_setup_logger 开始: {self.__class__.__name__}")
        import yaml

        # 直接加载全局 config.yaml
        try:
            print("加载 config.yaml...")
            with open("config.yaml", "r", encoding="utf-8") as f:
                global_config = yaml.safe_load(f)
            log_dir = global_config.get("logging", {}).get("directory", "logs")
            print(f"从 config.yaml 获取日志目录: {log_dir}")
        except Exception as e:
            print(f"[日志调试] 加载 config.yaml 失败: {e}")
            log_dir = "logs"
        print(
            f"[日志调试] handler 日志目录: {log_dir}, 绝对路径: {os.path.abspath(log_dir)}"
        )

        # Create logs directory if it doesn't exist (supports relative paths)
        print("检查并创建日志目录...")
        if not os.path.exists(log_dir):
            print(f"创建日志目录: {log_dir}")
            os.makedirs(log_dir)
        print("日志目录检查完成")

        # Get current date for log file name
        current_date = datetime.now().strftime("%Y-%m-%d")
        log_file = f"{log_dir}/{self.__class__.__name__}_{current_date}.log"

        # Create logger
        logger = logging.getLogger(self.__class__.__name__)

        # Clear any existing handlers
        if logger.hasHandlers():
            logger.handlers.clear()

        logger.setLevel(logging.DEBUG)

        # Create file handler
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)

        # Create formatter
        formatter = logging.Formatter(
            "[%(levelname)s]%(funcName)s:%(lineno)d - %(message)s"
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
            self.logger.warning(
                f"Element not found within {timeout} seconds: {locator_value}"
            )
            self.logger.warning(f"Error: {str(e)}")
            return None

    def wait_for_element_plus(self, element_key: str, timeout: int = 10) -> WebElement:
        """Enhanced wait_for_element using just element key"""
        try:
            locator_type, value = self._get_locator(element_key)
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((locator_type, value))
            )
            self.logger.debug(f"Found  element: {element_key}")
            return element
        except TimeoutException as e:
            self.logger.warning(
                f"Element {element_key}:{value} not found within {timeout} seconds "
            )
            return None
        except WebDriverException as e:
            self.logger.error(f"Trace: {traceback.format_exc()}")
            self.logger.error(f"Error: {str(e)}")

            # Check if this is a UiAutomator2 crash and handle it
            if self._is_uiautomator2_crash(e):
                self.logger.warning(
                    "Detected UiAutomator2 server crash in wait_for_element_plus, attempting recovery..."
                )
                if self._handle_uiautomator2_crash():
                    # Retry the operation after successful recovery
                    try:
                        locator_type, value = self._get_locator(element_key)
                        element = WebDriverWait(self.driver, timeout).until(
                            EC.presence_of_element_located((locator_type, value))
                        )
                        self.logger.debug(
                            f"Found element after recovery: {element_key}"
                        )
                        return element
                    except Exception as retry_e:
                        self.logger.error(
                            f"Retry failed after UiAutomator2 recovery: {str(retry_e)}"
                        )
                        return None
                else:
                    self.logger.error("UiAutomator2 recovery failed")
                    return None

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

    def wait_for_element_clickable_plus(
            self, element_key: str, timeout: int = 10
    ) -> WebElement:
        """Enhanced wait_for_element using just element key"""
        try:
            locator_type, value = self._get_locator(element_key)
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((locator_type, value))
            )
            self.logger.debug(f"Found clickable element: {element_key}")
            return element
        except TimeoutException as e:
            self.logger.warning(
                f"Clickable element {element_key}:{value} not found within {timeout} seconds "
            )
            return None
        except StaleElementReferenceException as e:
            self.logger.warning(f"Stale element reference for {element_key}:{value}")
            return None
        except WebDriverException as e:
            self.logger.error(f"Trace: {traceback.format_exc()}")
            self.logger.error(f"Error: {str(e)}")

            # Check if this is a UiAutomator2 crash and handle it
            if self._is_uiautomator2_crash(e):
                self.logger.warning(
                    "Detected UiAutomator2 server crash, attempting recovery..."
                )
                if self._handle_uiautomator2_crash():
                    # Retry the operation after successful recovery
                    try:
                        locator_type, value = self._get_locator(element_key)
                        element = WebDriverWait(self.driver, timeout).until(
                            EC.element_to_be_clickable((locator_type, value))
                        )
                        self.logger.debug(
                            f"Found clickable element after recovery: {element_key}"
                        )
                        return element
                    except Exception as retry_e:
                        self.logger.error(
                            f"Retry failed after UiAutomator2 recovery: {str(retry_e)}"
                        )
                        return None
                else:
                    self.logger.error("UiAutomator2 recovery failed")
                    return None

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
            self.logger.warning(
                f"Clickable element not found within {timeout} seconds: {locator_value}"
            )
            return None
        except WebDriverException as e:
            self.logger.error(f"Trace: {traceback.format_exc()}")
            self.logger.error(f"Error: {str(e)}")

            # Check if this is a UiAutomator2 crash and handle it
            if self._is_uiautomator2_crash(e):
                self.logger.warning(
                    "Detected UiAutomator2 server crash, attempting recovery..."
                )
                if self._handle_uiautomator2_crash():
                    # Retry the operation after successful recovery
                    try:
                        element = WebDriverWait(self.driver, timeout).until(
                            EC.element_to_be_clickable((locator_type, locator_value))
                        )
                        self.logger.debug(
                            f"Found clickable element after recovery: {locator_value}"
                        )
                        return element
                    except Exception as retry_e:
                        self.logger.error(
                            f"Retry failed after UiAutomator2 recovery: {str(retry_e)}"
                        )
                        return None
                else:
                    self.logger.error("UiAutomator2 recovery failed")
                    return None

            return None

    def switch_to_app(self):
        """Switch to specified app"""
        try:
            self.driver.activate_app(self.config["package_name"])
        except WebDriverException as e:
            # Check if this is a UiAutomator2 crash and handle it
            if self._is_uiautomator2_crash(e):
                self.logger.warning(
                    "Detected UiAutomator2 server crash in switch_to_app, attempting recovery..."
                )
                if self._handle_uiautomator2_crash():
                    # Retry the operation after successful recovery
                    try:
                        self.driver.activate_app(self.config["package_name"])
                    except Exception as retry_e:
                        self.logger.error(
                            f"Retry failed after UiAutomator2 recovery in switch_to_app: {str(retry_e)}"
                        )
                        return False
                else:
                    self.logger.error("UiAutomator2 recovery failed in switch_to_app")
                    return False
            else:
                self.logger.error(f"Failed to switch to app: {str(e)}")
                return False

        time.sleep(0.1)
        return True

    def close_app(self):
        """关闭应用"""
        self.driver.terminate_app(self.config["package_name"])

    def switch_to_activity(self, activity):
        """Switch to the specified activity"""
        package_name = self.config["package_name"]
        command = f"am start -n {package_name}/{activity}"
        self.driver.execute_script("mobile: shell", {"command": command})

    def press_enter(self, element):
        """
        Press Enter key on the given element
        Args:
            element: The WebElement to send Enter key to
        """
        self.driver.press_keycode(66)
        self.logger.debug("Pressed Return Key")

    def press_back(self):
        """Press Android back button"""
        try:
            self.driver.press_keycode(4)  # Android back key code
        except WebDriverException as e:
            # Check if this is a UiAutomator2 crash and handle it
            if self._is_uiautomator2_crash(e):
                self.logger.warning(
                    "Detected UiAutomator2 server crash in press_back, attempting recovery..."
                )
                if self._handle_uiautomator2_crash():
                    # Retry the operation after successful recovery
                    try:
                        self.driver.press_keycode(4)  # Android back key code
                        self.error_count = 0
                        self.logger.debug("Pressed back button after recovery")
                        return True
                    except Exception as retry_e:
                        self.error_count += 1
                        self.logger.error(
                            f"Retry failed after UiAutomator2 recovery in press_back: {str(retry_e)}"
                        )
                        return False
                else:
                    self.error_count += 1
                    self.logger.error("UiAutomator2 recovery failed in press_back")
                    return False
            else:
                self.error_count += 1
                self.logger.error(
                    f"Failed to press back button, times: {self.error_count}, trace:{traceback.format_exc()} error: {str(e)}"
                )
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
                "mobile: shell", {"command": "input keyevent KEYCODE_DPAD_RIGHT"}
            )
            time.sleep(0.1)  # Small delay between key presses

    def try_find_element_plus(
            self, element_key: str, log=False, clickable=False
    ) -> WebElement:
        """Enhanced try_find_element using just element key"""
        try:
            if log:
                self.logger.info(f"Looking for element '{element_key}'")

            if element_key not in self.config["elements"]:
                if log:
                    self.logger.error(
                        f"Element key '{element_key}' not defined in configuration"
                    )
                return None

            locator_type, value = self._get_locator(element_key)
            if log:
                self.logger.info(
                    f"Using locator type {locator_type} with value '{value}'"
                )

            try:
                element = self.driver.find_element(locator_type, value)
                if element:
                    if log:
                        try:
                            element_text = element.text
                            element_attrs = {
                                "displayed": element.is_displayed(),
                                "enabled": element.is_enabled(),
                                "text": element_text,
                            }
                            # Try to get additional attributes
                            for attr in ["content-desc", "resource-id", "className"]:
                                element_attrs[attr] = element.get_attribute(attr)

                            self.logger.info(
                                f"Found element '{element_key}': {element_attrs}"
                            )
                        except Exception as attr_e:
                            self.logger.warning(
                                f"Found element '{element_key}' but couldn't get attributes: {str(attr_e)}"
                            )

                    if clickable:
                        if log:
                            self.logger.info(
                                f"Waiting for element '{element_key}' to be clickable"
                            )
                        element = self.wait_for_element_clickable_plus(element_key)
                        if element and log:
                            self.logger.info(
                                f"Element '{element_key}' is now clickable"
                            )
                return element
            except WebDriverException as find_e:
                # Check if this is a UiAutomator2 crash and handle it
                if self._is_uiautomator2_crash(find_e):
                    self.logger.warning(
                        "Detected UiAutomator2 server crash in try_find_element_plus, attempting recovery..."
                    )
                    if self._handle_uiautomator2_crash():
                        # Retry the operation after successful recovery
                        try:
                            element = self.driver.find_element(locator_type, value)
                            if element and clickable:
                                element = self.wait_for_element_clickable_plus(
                                    element_key
                                )
                            return element
                        except Exception as retry_e:
                            if log:
                                self.logger.warning(
                                    f"Retry failed after UiAutomator2 recovery: {str(retry_e)}"
                                )
                            return None
                    else:
                        self.logger.error(
                            "UiAutomator2 recovery failed in try_find_element_plus"
                        )
                        return None
                else:
                    if log:
                        self.logger.warning(
                            f"Failed to find element '{element_key}' with value '{value}': {str(find_e)}"
                        )
                    return None
            except Exception as find_e:
                if log:
                    self.logger.warning(
                        f"Failed to find element '{element_key}' with value '{value}': {str(find_e)}"
                    )
                return None

        except Exception as e:
            if log:
                self.logger.warning(
                    f"Error in try_find_element_plus for '{element_key}': {str(e)}"
                )
            return None

    def try_find_element(self, locator_type, locator_value, log=True, clickable=False):
        """Try to find element and return it"""
        try:
            element = self.driver.find_element(locator_type, locator_value)
            if element and clickable:
                element = self.wait_for_element_clickable(locator_type, locator_value)
            return element
        except WebDriverException as e:
            # Check if this is a UiAutomator2 crash and handle it
            if self._is_uiautomator2_crash(e):
                self.logger.warning(
                    "Detected UiAutomator2 server crash in try_find_element, attempting recovery..."
                )
                if self._handle_uiautomator2_crash():
                    # Retry the operation after successful recovery
                    try:
                        element = self.driver.find_element(locator_type, locator_value)
                        if element and clickable:
                            element = self.wait_for_element_clickable(
                                locator_type, locator_value
                            )
                        return element
                    except Exception as retry_e:
                        if log:
                            self.logger.warning(
                                f"Retry failed after UiAutomator2 recovery: {str(retry_e)}"
                            )
                        return None
                else:
                    self.logger.error(
                        "UiAutomator2 recovery failed in try_find_element"
                    )
                    return None
            else:
                if log:
                    self.logger.warning(f"Element not found: {locator_value}")
                return None
        except Exception as e:
            if log:
                self.logger.warning(
                    f"Element not found: {locator_value}, error: {str(e)}"
                )
            return None

    def wait_for_element_polling(
            self, locator_type, locator_value, timeout=10, poll_frequency=0.5
    ):
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
        self.logger.warning(
            f"Element not found after polling for {timeout} seconds: {locator_value}"
        )
        return None

    def wait_for_element_clickable_polling(
            self, locator_type, locator_value, timeout=10, poll_frequency=0.5
    ):
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
                    self.logger.debug(
                        f"Found clickable element after polling: {locator_value}"
                    )
                    return element
            except Exception:
                pass
            time.sleep(poll_frequency)
            self.logger.debug(f"Polling for clickable element: {locator_value}")
        self.logger.warning(
            f"Clickable element not found after polling for {timeout} seconds: {locator_value}"
        )
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
            self.logger.warning(
                f"Unable to get  attribute {attribute}: Element is no longer attached to the DOM."
            )
            return None

    def _get_locator(self, element_key: str) -> tuple:
        """Helper to get locator type and value from element key"""
        if element_key not in self.config["elements"]:
            raise ValueError(f"Element key '{element_key}' not found in config")

        value = self.config["elements"][element_key]
        locator_type = AppiumBy.XPATH if value.startswith("//") else AppiumBy.ID
        return locator_type, value

    def find_elements_plus(self, element_key: str) -> list:
        """Enhanced find_elements using just element key"""
        try:
            locator_type, value = self._get_locator(element_key)
            return self.driver.find_elements(locator_type, value)
        except Exception as e:
            print(
                f"Failed to find elements '{element_key}' with value '{value}': {str(e)}"
            )
            return []

    def click_element_at(
            self, element, x_ratio=0.5, y_ratio=0.5, x_offset=0, y_offset=0
    ):
        """Click element at specified position ratio
        Args:
            element: WebElement to click
            x_ratio: float, horizontal position ratio (0.0 to 1.0), default 0.5 for center
            y_ratio: float, vertical position ratio (0.0 to 1.0), default 0.5 for center
        Returns:
            bool: True if click successful, False otherwise
        """
        try:
            if not element:
                return False

            # Get element size and location
            size = element.size
            location = element.location

            # Calculate click position
            click_x = location["x"] + int(x_offset) + int(size["width"] * x_ratio)
            click_y = location["y"] + int(y_offset) + int(size["height"] * y_ratio)
            if click_y < 110:
                self.logger.warning(
                    f"Click position is too top, click_x: {click_x}, click_y: {click_y}"
                )
                click_y = 110

            # Perform tap action at calculated position
            actions = ActionChains(self.driver)
            actions.w3c_actions = ActionBuilder(
                self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch")
            )
            actions.w3c_actions.pointer_action.move_to_location(click_x, click_y)
            actions.w3c_actions.pointer_action.pointer_down()
            actions.w3c_actions.pointer_action.pause(0.1)
            actions.w3c_actions.pointer_action.pointer_up()
            actions.perform()

            self.logger.debug(f"Clicked element at position ({click_x}, {click_y})")
            return True

        except Exception as e:
            self.logger.error(f"Error clicking element: {traceback.format_exc()}")
            return False

    def find_child_element_plus(self, parent, element_key):
        """Find child element using element key from config
        Args:
            parent: Parent element to search within
            element_key: Key in config elements section
        Returns:
            WebElement or None if not found
        """
        try:
            element_id = self.config["elements"][element_key]
            if element_id.startswith("//"):
                return self.find_child_element(parent, AppiumBy.XPATH, element_id)
            else:
                return self.find_child_element(parent, AppiumBy.ID, element_id)
        except Exception as e:
            self.logger.debug(f"Failed to find child element {element_key}: {str(e)}")
            return None

    def _perform_swipe(
            self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300
    ) -> bool:
        """在指定坐标执行一次滑动。
        Args:
            start_x: 起点 X
            start_y: 起点 Y
            end_x: 终点 X
            end_y: 终点 Y
            duration_ms: 按下到抬起的持续时间（毫秒）
        Returns:
            bool: 是否执行成功
        """
        try:
            actions = ActionChains(self.driver)
            actions.w3c_actions = ActionBuilder(
                self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch")
            )
            actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
            actions.w3c_actions.pointer_action.pointer_down()
            # 将持续时间拆分为多个小步，提升稳定性
            steps = max(1, int(duration_ms / 50))
            delta_x = (end_x - start_x) / steps
            delta_y = (end_y - start_y) / steps
            current_x = start_x
            current_y = start_y
            for _ in range(steps):
                current_x += delta_x
                current_y += delta_y
                actions.w3c_actions.pointer_action.move_to_location(
                    int(current_x), int(current_y)
                )
                actions.w3c_actions.pointer_action.pause(0.05)
            actions.w3c_actions.pointer_action.pointer_up()
            actions.perform()
            return True
        except Exception:
            self.logger.error(f"Error performing swipe: {traceback.format_exc()}")
            return False

    def scroll_container_until_element(
            self, element_key: str, container_key: str, direction: str = "up"
    ) -> Tuple[Optional[str], Optional[WebElement]]:
        """在指定容器内滚动，直到找到目标元素或无法继续滚动。

        参数：
            element_key: 目标元素在配置中的 key（应为容器的子元素）
            container_key: 容器元素在配置中的 key
            direction: 滚动方向，支持 'up'|'down'|'left'|'right'，默认 'up'（自下向上）

        策略：
            以 'up' 为例：每次从容器可视部分约 80% 处滑动到容器顶部附近（约 10%），滑动后尝试查找子元素；
            若找到则返回 (element_key, element)。若连续滑动后页面不再变化（page_source 无变化），则认为到达边界，返回 (None, None)。

        返回：
            (key, element) 或 (None, None)
        """
        try:
            # 获取容器
            container = self.wait_for_element_clickable_plus(container_key)
            if not container:
                self.logger.warning(
                    f"scroll_container_until_element: 容器未找到: {container_key}"
                )
                return None, None

            # 方向规范化
            valid_dirs = {"up", "down", "left", "right"}
            if direction not in valid_dirs:
                self.logger.warning(
                    f"scroll_container_until_element: 非法方向 {direction}，使用默认 'up'"
                )
                direction = "up"

            # 预计算容器可视坐标
            loc = container.location
            size = container.size
            left = int(loc["x"])
            top = int(loc["y"])
            width = int(size["width"])
            height = int(size["height"])

            # 单次滑动的起止点计算（默认 'up'）
            def compute_points(dir_name: str):
                if dir_name == "up":
                    start_x = left + int(width * 0.5)
                    start_y = top + int(height * 0.8)
                    end_x = left + int(width * 0.5)
                    end_y = top + int(height * 0.1)
                    return start_x, start_y, end_x, end_y
                if dir_name == "down":
                    start_x = left + int(width * 0.5)
                    start_y = top + int(height * 0.2)
                    end_x = left + int(width * 0.5)
                    end_y = top + int(height * 0.9)
                    return start_x, start_y, end_x, end_y
                if dir_name == "left":
                    start_x = left + int(width * 0.8)
                    start_y = top + int(height * 0.5)
                    end_x = left + int(width * 0.1)
                    end_y = top + int(height * 0.5)
                    return start_x, start_y, end_x, end_y
                # right
                start_x = left + int(width * 0.2)
                start_y = top + int(height * 0.5)
                end_x = left + int(width * 0.9)
                end_y = top + int(height * 0.5)
                return start_x, start_y, end_x, end_y

            # 页面无变化检测：通过 page_source 哈希判断
            def snapshot() -> int:
                try:
                    return hash(self.driver.page_source)
                except Exception:
                    return 0

            # 开始循环滑动查找
            prev_hash = snapshot()
            stable_rounds = 0
            max_stable_rounds = 2  # 连续多次无变化则认为到达边界
            max_swipes = 50

            for _ in range(max_swipes):
                # 尝试在容器内查找目标
                found = self.find_child_element_plus(container, element_key)
                if found:
                    return element_key, found

                # 计算滑动坐标并执行滑动
                sx, sy, ex, ey = compute_points(direction)
                ok = self._perform_swipe(sx, sy, ex, ey, duration_ms=400)
                if not ok:
                    self.logger.warning(
                        "scroll_container_until_element: 滑动失败，终止"
                    )
                    return None, None

                time.sleep(0.35)

                # 滑动后再试一次（元素可能已进入可视区）
                found = self.find_child_element_plus(container, element_key)
                if found:
                    return element_key, found

                # 判断是否到底/到边（页面无变化）
                cur_hash = snapshot()
                if cur_hash == prev_hash:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    prev_hash = cur_hash

                if stable_rounds >= max_stable_rounds:
                    self.logger.info(
                        "scroll_container_until_element: 已到达边界，未找到目标元素"
                    )
                    return None, None

            self.logger.info(
                "scroll_container_until_element: 达到最大滑动次数，未找到目标元素"
            )
            return None, None
        except WebDriverException as e:
            # UiAutomator2 崩溃处理
            if self._is_uiautomator2_crash(e):
                self.logger.warning(
                    "Detected UiAutomator2 server crash in scroll_container_until_element, attempting recovery..."
                )
                if self._handle_uiautomator2_crash():
                    try:
                        return self.scroll_container_until_element(
                            element_key, container_key, direction
                        )
                    except Exception as retry_e:
                        self.logger.error(
                            f"Retry failed after UiAutomator2 recovery: {str(retry_e)}"
                        )
                        return None, None
                else:
                    self.logger.error(
                        "UiAutomator2 recovery failed in scroll_container_until_element"
                    )
                    return None, None
            else:
                self.logger.error(
                    f"scroll_container_until_element error: {traceback.format_exc()}"
                )
                return None, None
        except Exception:
            self.logger.error(
                f"scroll_container_until_element error: {traceback.format_exc()}"
            )
            return None, None

    def wait_for_any_element_plus(
            self, element_keys: list, timeout: int = 10
    ) -> Tuple[Optional[str], Optional[WebElement]]:
        """
        等待任意一个元素出现。

        Args:
            element_keys: 元素key列表（配置中的elements键）
            timeout: 超时时间（秒）

        Returns:
            (key, element): 若找到则返回对应的元素key和元素对象
            (None, None): 超时或未找到时返回
        """
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        locators = []
        key_map = {}
        for key in element_keys:
            if key not in self.config["elements"]:
                continue
            value = self.config["elements"][key]
            locator_type = AppiumBy.XPATH if value.startswith("//") else AppiumBy.ID
            locators.append((locator_type, value))
            key_map[(locator_type, value)] = key

        if not locators:
            self.logger.warning("wait_for_any_element_plus: 没有有效的元素key")
            return None, None

        try:
            # Selenium 4.8+ 支持 EC.any_of
            element = WebDriverWait(self.driver, timeout).until(
                EC.any_of(
                    *[EC.presence_of_element_located(locator) for locator in locators]
                )
            )
            # 找到是哪个key
            for locator, key in key_map.items():
                try:
                    found = self.driver.find_element(*locator)
                    if found and found.id == element.id:
                        return key, element
                except Exception:
                    continue
            self.logger.warning("wait_for_any_element_plus: 找不到对应的key")
            return None, None
        except WebDriverException as e:
            # Check if this is a UiAutomator2 crash and handle it
            if self._is_uiautomator2_crash(e):
                self.logger.warning(
                    "Detected UiAutomator2 server crash in wait_for_any_element_plus, attempting recovery..."
                )
                if self._handle_uiautomator2_crash():
                    # Retry the operation after successful recovery
                    try:
                        element = WebDriverWait(self.driver, timeout).until(
                            EC.any_of(
                                *[
                                    EC.presence_of_element_located(locator)
                                    for locator in locators
                                ]
                            )
                        )
                        # 找到是哪个key
                        for locator, key in key_map.items():
                            try:
                                found = self.driver.find_element(*locator)
                                if found and found.id == element.id:
                                    return key, element
                            except Exception:
                                continue
                        self.logger.warning(
                            "wait_for_any_element_plus: 找不到对应的key"
                        )
                        return None, None
                    except Exception as retry_e:
                        self.logger.error(
                            f"Retry failed after UiAutomator2 recovery: {str(retry_e)}"
                        )
                        return None, None
                else:
                    self.logger.error("UiAutomator2 recovery failed")
                    return None, None
            else:
                self.logger.error(
                    f"wait_for_any_element_plus: {element_keys} 超时未找到任何元素: {str(e)}"
                )
                return None, None
        except Exception as e:
            self.logger.error(
                f"wait_for_any_element_plus: {element_keys} 超时未找到任何元素: {str(e)}"
            )
            return None, None

    def _is_uiautomator2_crash(self, exception: Exception) -> bool:
        """
        Check if the exception indicates a UiAutomator2 server crash
        Args:
            exception: The exception to check
        Returns:
            bool: True if it's a UiAutomator2 crash, False otherwise
        """
        error_message = str(exception).lower()
        crash_indicators = [
            "uiautomator2 server",
            "instrumentation process is not running",
            "probably crashed",
            "cannot be proxied to uiautomator2 server",
        ]
        return any(indicator in error_message for indicator in crash_indicators)

    def _reinitialize_driver(self) -> bool:
        """
        Reinitialize the driver when UiAutomator2 crashes
        Returns:
            bool: True if reinitialization was successful, False otherwise
        """
        try:
            self.logger.warning(
                "UiAutomator2 server crashed, attempting to reinitialize driver..."
            )

            # Close the current driver
            try:
                self.driver.quit()
            except Exception as e:
                self.logger.debug(f"Error closing driver: {str(e)}")

            # Wait a moment for cleanup
            time.sleep(2)

            # Reinitialize the driver using the controller's method
            self.driver = self.controller._init_driver()

            # Update the driver reference in the controller
            self.controller.driver = self.driver

            # Update driver references in handlers
            self.controller.soul_handler.driver = self.driver
            self.controller.music_handler.driver = self.driver

            # Switch back to the app
            self.switch_to_app()

            self.logger.info("Driver reinitialization completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to reinitialize driver: {str(e)}")
            return False

    def navigate_to_element(
            self,
            target_key: str,
            interference_keys: list = None,
            home_key: str = "home_nav",
            back_keys=None,
            max_attempts: int = 10,
    ) -> Tuple[Optional[str], Optional[WebElement]]:
        """
        导航到目标元素，通过检测当前页面状态并执行相应操作

        Args:
            home_key: 首页元素key，找到表示已回到首页，不能再返回
            back_keys: 返回按钮key列表，找到则点击返回上一页
            target_key: 目标元素key，找到则直接返回
            interference_keys: 干扰元素key列表，出现则按系统返回键隐藏
            max_attempts: 最大尝试次数，防止无限循环

        Returns:
            (key, element): 找到的元素key和元素对象
            (None, None): 未找到或出错时返回
        """
        if back_keys is None:
            back_keys = ["go_back", "minimize_screen"]
        if interference_keys is None:
            interference_keys = []

        self.logger.info(f"开始导航到目标元素: {target_key}")
        self.press_back()

        for attempt in range(max_attempts):
            self.logger.debug(f"导航尝试 {attempt + 1}/{max_attempts}")

            # 构建检测元素列表，按优先级排序：干扰元素 -> 目标元素 -> 返回按钮 -> home元素
            check_keys = interference_keys + [target_key] + back_keys + [home_key]

            # 使用 wait_for_any_element_plus 检测当前状态
            found_key, found_element = self.wait_for_any_element_plus(check_keys)

            if not found_element:
                self.logger.warning(f"第 {attempt + 1} 次尝试：未检测到任何元素")
                # 按系统返回键尝试返回
                self.press_back()
                return None, None

            # 根据找到的元素类型执行相应操作
            if found_key == target_key:
                self.logger.info(f"找到目标元素: {target_key}")
                return found_key, found_element

            elif found_key in back_keys:
                if self.click_element_at(found_element):
                    self.logger.info(f"找到返回按钮: {found_key}，点击返回")
                else:
                    self.logger.warning(f"点击返回按钮失败: {found_key}")
                    # 尝试系统返回键作为备选
                    self.press_back()

            elif found_key in interference_keys:
                self.logger.info(f"发现干扰元素: {found_key}，按系统返回键隐藏")
                if not self.press_back():
                    self.logger.error("按系统返回键失败")
                    return None, None

            elif found_key == home_key:
                self.logger.warning(f"已回到首页: {home_key}，无法继续返回")
                return found_key, found_element

            else:
                self.logger.warning(f"检测到未知元素: {found_key}")
                self.press_back()
                return None, None

        # 达到最大尝试次数
        self.logger.error(f"导航失败：达到最大尝试次数 {max_attempts}")
        return None, None

    def _handle_uiautomator2_crash(self) -> bool:
        """
        Handle UiAutomator2 server crash by reinitializing the driver
        Returns:
            bool: True if recovery was successful, False otherwise
        """
        if self._reinitialize_driver():
            self.error_count = 0  # Reset error count on successful recovery
            return True
        else:
            self.error_count += 1
            return False
