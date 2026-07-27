import logging

from ushareiplay.core.log_formatter import ColoredFormatter
from ushareiplay.core.ui import ElementFinder, GestureHandler, KeyActions, Navigator, UIActions

_shared_handler_file_handler = None
_shared_handler_file_path = None


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
        self.ui_actions = UIActions(self)
        self.logger.debug(f"AppHandler.__init__ 完成: {self.__class__.__name__}")

    @property
    def driver_recovery_context(self):
        return getattr(self.controller, "driver_recovery_context", None)

    def _setup_logger(self):
        """Setup logger for the handler.

        Delegates to the RuntimeLogging module so path resolution, archiving,
        handler construction, and reset behavior share one implementation
        across the app log and the chat log.
        """
        from ushareiplay.core.runtime_logging import get_runtime_logging

        cfg = None
        if getattr(self, "controller", None) is not None:
            cfg = getattr(self.controller, "config", None)
        return get_runtime_logging().attach_app_logger(
            self.__class__.__name__, cfg
        )

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
