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
        """Setup logger for the handler
        Returns:
            logging.Logger: Configured logger instance
        """
        global _shared_handler_file_handler, _shared_handler_file_path

        from ushareiplay.core.log_rotation import archive_active_log_on_startup
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
        log_file_path = log_dir_path / "UShareIPlay.log"

        # Create logger
        logger = logging.getLogger(self.__class__.__name__)

        # Clear any existing handlers
        if logger.hasHandlers():
            logger.handlers.clear()

        logger.setLevel(logging.DEBUG)

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

        if (
            _shared_handler_file_handler is None
            or _shared_handler_file_path != log_file_path
        ):
            if _shared_handler_file_handler is not None:
                _shared_handler_file_handler.close()
            log_file_path = archive_active_log_on_startup(log_dir_path, "UShareIPlay.log")
            _shared_handler_file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
            _shared_handler_file_handler.setLevel(logging.DEBUG)
            _shared_handler_file_path = log_file_path

        _shared_handler_file_handler.setFormatter(file_formatter)
        console_handler.setFormatter(console_formatter)

        # Add handlers to logger
        logger.addHandler(_shared_handler_file_handler)
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
