"""Interface tests for the runtime logging lifecycle seam."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def test_attach_app_logger_archives_existing_active_file(tmp_path: Path, monkeypatch):
    from ushareiplay.core.runtime_logging import RuntimeLogging

    monkeypatch.setattr(
        "ushareiplay.core.log_rotation._log_file_created_at",
        lambda path: datetime(2026, 7, 9, 8, 7, 6),
    )

    active = tmp_path / "UShareIPlay.log"
    active.write_text("old app\n", encoding="utf-8")

    lifecycle = RuntimeLogging()
    logger = lifecycle.attach_app_logger(
        "test.AppHandler", {"logging": {"directory": str(tmp_path)}}
    )
    try:
        logger.info("hello")
        for handler in logger.handlers:
            handler.flush()

        assert (tmp_path / "UShareIPlay_2026-07-09_08-07-06.log").read_text(
            encoding="utf-8"
        ) == "old app\n"
        assert "hello" in active.read_text(encoding="utf-8")
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        lifecycle.reset()


def test_attach_app_logger_shares_handler_across_calls(tmp_path: Path, monkeypatch):
    from ushareiplay.core.runtime_logging import RuntimeLogging

    monkeypatch.setattr(
        "ushareiplay.core.log_rotation._log_file_created_at",
        lambda path: datetime(2026, 7, 9, 8, 7, 6),
    )

    lifecycle = RuntimeLogging()
    logger_a = lifecycle.attach_app_logger(
        "test.HandlerA", {"logging": {"directory": str(tmp_path)}}
    )
    logger_b = lifecycle.attach_app_logger(
        "test.HandlerB", {"logging": {"directory": str(tmp_path)}}
    )
    try:
        file_handlers_a = [
            h for h in logger_a.handlers if isinstance(h, logging.FileHandler)
        ]
        file_handlers_b = [
            h for h in logger_b.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers_a) == 1
        assert len(file_handlers_b) == 1
        # Same path -> same handler.
        assert file_handlers_a[0].stream.name == file_handlers_b[0].stream.name
    finally:
        for logger in (logger_a, logger_b):
            for handler in logger.handlers:
                handler.close()
            logger.handlers.clear()
        lifecycle.reset()


def test_attach_chat_logger_archives_existing_active_file(tmp_path: Path, monkeypatch):
    from ushareiplay.core.runtime_logging import RuntimeLogging

    monkeypatch.setattr(
        "ushareiplay.core.log_rotation._log_file_created_at",
        lambda path: datetime(2026, 7, 9, 8, 7, 6),
    )

    active = tmp_path / "chat.log"
    active.write_text("old chat\n", encoding="utf-8")

    lifecycle = RuntimeLogging()
    logger = lifecycle.attach_chat_logger({"logging": {"directory": str(tmp_path)}})
    try:
        logger.info("hi from chat")
        for handler in logger.handlers:
            handler.flush()

        assert (tmp_path / "chat_2026-07-09_08-07-06.log").read_text(
            encoding="utf-8"
        ) == "old chat\n"
        assert "hi from chat" in active.read_text(encoding="utf-8")
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        lifecycle.reset()


def test_reset_closes_shared_handlers_and_clears_state(tmp_path: Path):
    from ushareiplay.core.runtime_logging import RuntimeLogging

    lifecycle = RuntimeLogging()
    logger = lifecycle.attach_app_logger(
        "test.Reset", {"logging": {"directory": str(tmp_path)}}
    )
    file_handlers = [
        h for h in logger.handlers if isinstance(h, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    assert len(lifecycle._shared_handlers) == 1

    lifecycle.reset()
    assert lifecycle._shared_handlers == {}
    assert lifecycle._console_handlers == {}

    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()


def test_resolve_path_returns_default_when_config_is_empty(tmp_path: Path, monkeypatch):
    from ushareiplay.core.runtime_logging import RuntimeLogging

    monkeypatch.setattr(
        "ushareiplay.core.config_loader.ConfigLoader.load_config",
        lambda: None,
    )

    lifecycle = RuntimeLogging()
    resolved = lifecycle.resolve_path({})

    # Falls back to a default_rel of "logs"; absolute path returned.
    assert resolved.is_absolute()


def test_shared_handler_is_idempotent_across_two_calls(tmp_path: Path):
    from ushareiplay.core.runtime_logging import RuntimeLogging

    lifecycle = RuntimeLogging()
    active = tmp_path / "UShareIPlay.log"
    active.write_text("only-once\n", encoding="utf-8")

    handler_one = lifecycle.shared_file_handler(
        active,
        archive_dir=tmp_path,
        archive_name="UShareIPlay.log",
    )
    handler_two = lifecycle.shared_file_handler(
        active,
        archive_dir=tmp_path,
        archive_name="UShareIPlay.log",
    )

    try:
        assert handler_one is handler_two
        # Only one archive per path across two attach calls.
        archives = list(tmp_path.glob("UShareIPlay_*.log"))
        assert len(archives) == 1
    finally:
        handler_one.close()
        lifecycle.reset()
