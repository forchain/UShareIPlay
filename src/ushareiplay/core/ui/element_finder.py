from __future__ import annotations

import time
from typing import Optional, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ushareiplay.core.driver_decorator import with_driver_recovery


class ElementFinder:
    def __init__(self, owner):
        self.owner = owner

    def __getattr__(self, name):
        return getattr(self.owner, name)

    @property
    def driver(self):
        return self.owner.driver

    @property
    def config(self):
        return self.owner.config

    @property
    def logger(self):
        return self.owner.logger

    @with_driver_recovery(op="read")
    def wait_for_element(self, element_key: str, timeout: int = 10) -> WebElement:
        """Enhanced wait_for_element using just element key"""
        try:
            locator_type, value = self._get_locator(element_key)
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((locator_type, value))
            )
            self.logger.debug(f"Found  element: {element_key}")
            return element
        except TimeoutException:
            self.logger.warning(
                f"Element {element_key}:{value} not found within {timeout} seconds "
            )
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

    @with_driver_recovery(op="read")
    def wait_for_element_clickable(
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
        except TimeoutException:
            self.logger.warning(
                f"Clickable element {element_key}:{value} not found within {timeout} seconds "
            )
            return None
        except StaleElementReferenceException:
            self.logger.warning(f"Stale element reference for {element_key}:{value}")
            return None

    @with_driver_recovery(op="read")
    def try_find_element(
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
                    element = self.wait_for_element_clickable(element_key)
                    if element and log:
                        self.logger.info(
                            f"Element '{element_key}' is now clickable"
                        )
            return element

        except Exception as e:
            if log:
                self.logger.warning(
                    f"Error in try_find_element for '{element_key}': {str(e)}"
                )
            return None

    @with_driver_recovery(op="read")
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

    @with_driver_recovery(op="read")
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

    @with_driver_recovery(op="read")
    def find_elements(self, element_key: str) -> list:
        """Enhanced find_elements using just element key"""
        try:
            locator_type, value = self._get_locator(element_key)
            return self.driver.find_elements(locator_type, value)
        except Exception as e:
            self.logger.warning(
                f"Failed to find elements '{element_key}' with value '{value}': {str(e)}"
            )
            return []

    def find_child_element(self, parent, element_key, log_failure: bool = True):
        """Find child element using element key from config
        Args:
            parent: Parent element to search within
            element_key: Key in config elements section
            log_failure: Whether to log when the child element is not found
        Returns:
            WebElement or None if not found
        """
        try:
            if not parent:
                return None
            locator_type, value = self._get_locator(element_key)
            return parent.find_element(locator_type, value)
        except Exception:
            if log_failure:
                self.logger.debug(f"Failed to find child element {element_key}")
            return None

    def find_child_elements(self, parent, element_key: str) -> list:
        """Find child elements using element key from config within a parent container.
        Args:
            parent: Parent WebElement to search within
            element_key: Key in config elements section
        Returns:
            List[WebElement]: child elements (empty list if not found / error)
        """
        try:
            if not parent:
                return []
            locator_type, value = self._get_locator(element_key)
            return parent.find_elements(locator_type, value)
        except Exception:
            self.logger.debug(
                f"Failed to find child elements {element_key}"
            )
            return []

    @with_driver_recovery(op="read")
    def wait_for_any_element(
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
            self.logger.warning("wait_for_any_element: 没有有效的元素key")
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
            self.logger.warning("wait_for_any_element: 找不到对应的key")
            return None, None
        except Exception as e:
            self.logger.error(
                f"wait_for_any_element: {element_keys} 超时未找到任何元素: {str(e)}"
            )
            return None, None

    def try_find_any_element(
            self, element_keys: list
    ) -> Tuple[Optional[str], Optional[WebElement]]:
        """
        无等待遍历查找任意一个元素。

        与 wait_for_any_element 的区别：
        - 不等待，不会因为元素不存在产生超时
        - 按给定 key 顺序返回第一个命中的元素
        """
        for key in element_keys:
            element = self.try_find_element(key, log=False)
            if element:
                return key, element
        return None, None
