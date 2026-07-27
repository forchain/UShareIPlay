"""Runtime logging lifecycle module.

One owner for path resolution, inode-safe archiving, handler construction,
and reset behavior. App handlers and chat loggers delegate here so the
lifecycle invariants (archive before write, shared handler per active
file, idempotent reset) live in a single seam.

Public surface:
- ``RuntimeLogging.resolve_path(config, default_rel)`` -- log directory.
- ``RuntimeLogging.attach_app_logger(name, config)`` -- shared app log.
- ``RuntimeLogging.attach_chat_logger(name, config)`` -- chat log.
- ``RuntimeLogging.reset()`` -- close shared handlers, clear module state.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


class RuntimeLogging:
    """Deep runtime logging lifecycle."""

    def __init__(self):
        # One shared file handler per active log file path. Keyed by the
        # resolved absolute path so two handlers pointing at the same file
        # share state instead of clobbering each other.
        self._shared_handlers: dict[Path, logging.FileHandler] = {}
        self._console_handlers: dict[str, logging.StreamHandler] = {}

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def resolve_path(
        self, config: Optional[dict], default_rel: str = "logs"
    ) -> Path:
        """Resolve the configured log directory, falling back to defaults."""
        from ushareiplay.core.config_loader import ConfigLoader
        from ushareiplay.core.paths import ensure_dir, resolve_log_directory

        cfg = config
        if not ((cfg or {}).get("logging", {}) or {}).get("directory", None):
            loaded = ConfigLoader.load_config()
            if loaded:
                cfg = loaded
        configured = ((cfg or {}).get("logging", {}) or {}).get("directory", "")
        log_dir_path = resolve_log_directory(configured, default_rel=default_rel)
        ensure_dir(log_dir_path)
        return log_dir_path

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def archive(self, log_dir: Path, active_name: str) -> Path:
        """Archive the active log file (inode-safe) and return the active path."""
        from ushareiplay.core.log_rotation import archive_active_log_on_startup

        return archive_active_log_on_startup(log_dir, active_name)

    # ------------------------------------------------------------------
    # File handler construction (shared per path)
    # ------------------------------------------------------------------

    def shared_file_handler(
        self,
        log_path: Path,
        *,
        archive_dir: Optional[Path] = None,
        archive_name: Optional[str] = None,
        encoding: str = "utf-8",
        formatter: Optional[logging.Formatter] = None,
        level: int = logging.DEBUG,
    ) -> logging.FileHandler:
        """Return a shared file handler for ``log_path``.

        On first construction for a path, the active file is archived so the
        handler starts writing into a fresh inode. Subsequent constructions
        reuse the handler (idempotent reset, no duplicate archives).
        """
        existing = self._shared_handlers.get(log_path)
        if existing is not None:
            return existing

        if archive_dir is not None and archive_name is not None:
            self.archive(archive_dir, archive_name)

        handler = logging.FileHandler(log_path, encoding=encoding)
        handler.setLevel(level)
        if formatter is not None:
            handler.setFormatter(formatter)
        self._shared_handlers[log_path] = handler
        return handler

    # ------------------------------------------------------------------
    # Logger attach helpers
    # ------------------------------------------------------------------

    def attach_app_logger(
        self, name: str, config: Optional[dict], *, level: int = logging.DEBUG
    ) -> logging.Logger:
        """Attach (or reuse) the shared app log + console handlers."""
        from ushareiplay.core.log_formatter import ColoredFormatter

        log_dir = self.resolve_path(config)
        active_path = log_dir / "UShareIPlay.log"

        file_formatter = ColoredFormatter(
            fmt="%(asctime)s [%(levelname)s]%(funcName)s:%(lineno)d - %(message)s",
            datefmt="%m-%d %H:%M:%S",
            use_colors=False,
        )
        console_formatter = ColoredFormatter(
            fmt="%(asctime)s [%(levelname)s]%(funcName)s:%(lineno)d - %(message)s",
            datefmt="%m-%d %H:%M:%S",
            use_colors=True,
        )

        file_handler = self.shared_file_handler(
            active_path,
            archive_dir=log_dir,
            archive_name="UShareIPlay.log",
            formatter=file_formatter,
            level=level,
        )
        console_handler = self._console_handlers.get(name)
        if console_handler is None:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(level)
            console_handler.setFormatter(console_formatter)
            self._console_handlers[name] = console_handler

        logger = logging.getLogger(name)
        if logger.hasHandlers():
            logger.handlers.clear()
        logger.setLevel(level)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        return logger

    def attach_chat_logger(
        self, config: Optional[dict], *, level: int = logging.INFO
    ) -> logging.Logger:
        """Attach (or reuse) the chat log + console handlers."""
        from ushareiplay.core.log_formatter import ColoredFormatter

        log_dir = self.resolve_path(config)
        active_path = log_dir / "chat.log"

        file_formatter = ColoredFormatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%m-%d %H:%M:%S",
            use_colors=False,
        )

        file_handler = self.shared_file_handler(
            active_path,
            archive_dir=log_dir,
            archive_name="chat.log",
            formatter=file_formatter,
            level=level,
        )

        logger = logging.getLogger("chat")
        if logger.hasHandlers():
            logger.handlers.clear()
        logger.setLevel(level)
        logger.addHandler(file_handler)
        return logger

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Close every shared handler and clear module state. Idempotent."""
        for handler in self._shared_handlers.values():
            try:
                handler.close()
            except Exception:
                pass
        self._shared_handlers.clear()

        for handler in self._console_handlers.values():
            try:
                handler.close()
            except Exception:
                pass
        self._console_handlers.clear()


_runtime_logging = RuntimeLogging()


def get_runtime_logging() -> RuntimeLogging:
    """Return the process-wide RuntimeLogging instance."""
    return _runtime_logging
