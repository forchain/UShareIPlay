import logging
import threading
from contextlib import contextmanager


class ConsoleLogMuter(logging.Filter):
    """Filter that mutes console log records when active."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._muted = False
        self._mutex = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ConsoleLogMuter":
        """Get or create the global singleton muter."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (mainly for tests)."""
        with cls._lock:
            cls._instance = None

    def mute(self) -> None:
        """Mute log output."""
        with self._mutex:
            self._muted = True

    def unmute(self) -> None:
        """Unmute log output."""
        with self._mutex:
            self._muted = False

    def is_muted(self) -> bool:
        """Return True if console logs are muted."""
        with self._mutex:
            return self._muted

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False to drop the record if muted, True otherwise."""
        with self._mutex:
            return not self._muted

    @contextmanager
    def paused(self):
        """Context manager to temporarily mute console logs."""
        self.mute()
        try:
            yield self
        finally:
            self.unmute()
