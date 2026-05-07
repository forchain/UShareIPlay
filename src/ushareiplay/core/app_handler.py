import logging
from datetime import datetime

from ushareiplay.core.log_formatter import ColoredFormatter
from ushareiplay.core.ui import ElementFinder, GestureHandler, KeyActions, Navigator


class AppHandler:
    def __init__(self, driver, config, controller):
        logging.getLogger(self.__class__.__name__).debug(f"AppHandler.__init__ 开始: {self.__class__.__name__}")
        self.driver = driver
        self.config = config
        logging.getLogger(self.__class__.__name__).debug(f"AppHandler 设置 logger: {self.__class__.__name__}")
        self.logger = self._setup_logger()
        self.logger.debug(f"AppHandler logger 设置完成: {self.__class__.__name__}")
        self.error_count = 0
        self.controller = controller
        self.element_finder = ElementFinder(self)
        self.key_actions = KeyActions(self)
        self.gesture_handler = GestureHandler(self)
        self.navigator = Navigator(self)
        self.logger.debug(f"AppHandler.__init__ 完成: {self.__class__.__name__}")

    @property
    def driver_recovery_context(self):
        return getattr(self.controller, "driver_recovery_context", None)

    def _setup_logger(self):
        """Setup logger for the handler
        Returns:
            logging.Logger: Configured logger instance
        """
        from ushareiplay.core.paths import ensure_dir, resolve_log_directory

        cfg = None
        if getattr(self, "controller", None) is not None:
            cfg = getattr(self.controller, "config", None)
        if not ((cfg or {}).get("logging", {}) or {}).get("directory", None):
            from ushareiplay.core.config_loader import ConfigLoader
            loaded = ConfigLoader.load_config()
            if loaded:
                cfg = loaded
        configured = ((cfg or {}).get("logging", {}) or {}).get("directory", "")
        log_dir_path = resolve_log_directory(configured, default_rel="logs")
        ensure_dir(log_dir_path)

        # Get current date for log file name
        current_date = datetime.now().strftime("%Y-%m-%d")
        log_file = str(log_dir_path / f"{self.__class__.__name__}_{current_date}.log")

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

        # Create formatters with timestamp and short level names
        # File formatter without colors
        file_formatter = ColoredFormatter(
            fmt="%(asctime)s [%(levelname)s]%(funcName)s:%(lineno)d - %(message)s",
            datefmt="%m-%d %H:%M:%S",
            use_colors=False
        )
        # Console formatter with colors
        console_formatter = ColoredFormatter(
            fmt="%(asctime)s [%(levelname)s]%(funcName)s:%(lineno)d - %(message)s",
            datefmt="%m-%d %H:%M:%S",
            use_colors=True
        )
        file_handler.setFormatter(file_formatter)
        console_handler.setFormatter(console_formatter)

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
        return self.element_finder.wait_for_element(locator_type, locator_value, timeout=timeout)

    def wait_for_element_plus(self, element_key: str, timeout: int = 10):
        return self.element_finder.wait_for_element_plus(element_key, timeout=timeout)

    def is_element_clickable(self, element):
        return self.element_finder.is_element_clickable(element)

    def wait_for_element_clickable_plus(self, element_key: str, timeout: int = 10):
        return self.element_finder.wait_for_element_clickable_plus(element_key, timeout=timeout)

    def wait_for_element_clickable(self, locator_type, locator_value, timeout=10):
        return self.element_finder.wait_for_element_clickable(locator_type, locator_value, timeout=timeout)

    def try_find_element_plus(self, element_key: str, log=False, clickable=False):
        return self.element_finder.try_find_element_plus(element_key, log=log, clickable=clickable)

    def try_find_element(self, locator_type, locator_value, log=True, clickable=False):
        return self.element_finder.try_find_element(locator_type, locator_value, log=log, clickable=clickable)

    def wait_for_element_polling(
            self, locator_type, locator_value, timeout=10, poll_frequency=0.5
    ):
        return self.element_finder.wait_for_element_polling(
            locator_type,
            locator_value,
            timeout=timeout,
            poll_frequency=poll_frequency,
        )

    def wait_for_element_clickable_polling(
            self, locator_type, locator_value, timeout=10, poll_frequency=0.5
    ):
        return self.element_finder.wait_for_element_clickable_polling(
            locator_type,
            locator_value,
            timeout=timeout,
            poll_frequency=poll_frequency,
        )

    def find_child_element(self, parent, locator_type, locator_value):
        return self.element_finder.find_child_element(parent, locator_type, locator_value)

    def find_child_elements(self, parent, locator_type, locator_value):
        return self.element_finder.find_child_elements(parent, locator_type, locator_value)

    def get_element_text(self, element):
        return self.element_finder.get_element_text(element)

    def try_get_attribute(self, element, attribute):
        return self.element_finder.try_get_attribute(element, attribute)

    def _get_locator(self, element_key: str):
        return self.element_finder._get_locator(element_key)

    def find_elements_plus(self, element_key: str):
        return self.element_finder.find_elements_plus(element_key)

    def find_child_element_plus(self, parent, element_key):
        return self.element_finder.find_child_element_plus(parent, element_key)

    def find_child_elements_plus(self, parent, element_key: str):
        return self.element_finder.find_child_elements_plus(parent, element_key)

    def wait_for_any_element_plus(self, element_keys: list, timeout: int = 10):
        return self.element_finder.wait_for_any_element_plus(element_keys, timeout=timeout)

    def try_find_any_element_plus(self, element_keys: list):
        return self.element_finder.try_find_any_element_plus(element_keys)

    def switch_to_app(self):
        return self.key_actions.switch_to_app()

    def close_app(self):
        return self.key_actions.close_app()

    def switch_to_activity(self, activity):
        return self.key_actions.switch_to_activity(activity)

    def press_enter(self, element):
        return self.key_actions.press_enter(element)

    def press_back(self):
        return self.key_actions.press_back()

    def press_dpad_down(self):
        return self.key_actions.press_dpad_down()

    def press_volume_up(self):
        return self.key_actions.press_volume_up()

    def press_volume_down(self):
        return self.key_actions.press_volume_down()

    def press_right_key(self, times=1):
        return self.key_actions.press_right_key(times=times)

    def set_clipboard_text(self, text):
        return self.key_actions.set_clipboard_text(text)

    def paste_text(self):
        return self.key_actions.paste_text()

    def click_element_at(
            self, element, x_ratio=0.5, y_ratio=0.5, x_offset=0, y_offset=0
    ):
        return self.gesture_handler.click_element_at(
            element,
            x_ratio=x_ratio,
            y_ratio=y_ratio,
            x_offset=x_offset,
            y_offset=y_offset,
        )

    def _reversed_if_needed(self, lst: list, direction: str):
        return self.gesture_handler._reversed_if_needed(lst, direction)

    def _perform_swipe(
            self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300
    ):
        return self.gesture_handler._perform_swipe(
            start_x,
            start_y,
            end_x,
            end_y,
            duration_ms=duration_ms,
        )

    def scroll_container_until_element(
            self, element_key: str, container_key: str, direction: str = "up", attribute_name: str = None,
            attribute_value: str = None, max_swipes: int = 10
    ):
        return self.gesture_handler.scroll_container_until_element(
            element_key,
            container_key,
            direction=direction,
            attribute_name=attribute_name,
            attribute_value=attribute_value,
            max_swipes=max_swipes,
        )

    def navigate_to_element(
            self,
            target_key: str,
            interference_keys: list = None,
            home_key: str = "home_nav",
            back_keys=None,
            max_attempts: int = 10,
    ):
        return self.navigator.navigate_to_element(
            target_key,
            interference_keys=interference_keys,
            home_key=home_key,
            back_keys=back_keys,
            max_attempts=max_attempts,
        )
