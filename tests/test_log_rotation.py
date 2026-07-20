from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


def test_archive_active_log_missing_file_does_not_create_archive(tmp_path: Path) -> None:
    from ushareiplay.core.log_rotation import archive_active_log_on_startup

    active = archive_active_log_on_startup(tmp_path, "UShareIPlay.log")

    assert active == tmp_path / "UShareIPlay.log"
    assert list(tmp_path.iterdir()) == []


def test_archive_active_log_empty_file_still_archives(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ushareiplay.core import log_rotation

    active_file = tmp_path / "UShareIPlay.log"
    active_file.touch()
    monkeypatch.setattr(
        log_rotation,
        "_log_file_created_at",
        lambda path: datetime(2026, 7, 9, 8, 7, 6),
    )

    active = log_rotation.archive_active_log_on_startup(tmp_path, "UShareIPlay.log")

    assert active == active_file
    assert active_file.exists()
    assert (tmp_path / "UShareIPlay_2026-07-09_08-07-06.log").exists()


def test_archive_active_log_uses_created_time_in_archive_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ushareiplay.core import log_rotation

    active_file = tmp_path / "UShareIPlay.log"
    active_file.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(
        log_rotation,
        "_log_file_created_at",
        lambda path: datetime(2026, 7, 9, 8, 7, 6),
    )

    active = log_rotation.archive_active_log_on_startup(tmp_path, "UShareIPlay.log")

    archive = tmp_path / "UShareIPlay_2026-07-09_08-07-06.log"
    assert active == active_file
    assert archive.read_text(encoding="utf-8") == "old\n"
    assert active_file.exists()
    assert active_file.read_text(encoding="utf-8") == ""


def test_archive_active_log_preserves_active_inode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ushareiplay.core import log_rotation

    active_file = tmp_path / "chat.log"
    active_file.write_text("old\n", encoding="utf-8")
    original_inode = active_file.stat().st_ino
    monkeypatch.setattr(
        log_rotation,
        "_log_file_created_at",
        lambda path: datetime(2026, 7, 9, 8, 7, 6),
    )

    log_rotation.archive_active_log_on_startup(tmp_path, "chat.log")

    assert active_file.stat().st_ino == original_inode
    assert active_file.read_text(encoding="utf-8") == ""


def test_app_handler_loggers_share_fixed_active_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ushareiplay.core import app_handler, log_rotation
    from ushareiplay.core.app_handler import AppHandler

    old_log = tmp_path / "UShareIPlay.log"
    old_log.write_text("old handler log\n", encoding="utf-8")
    monkeypatch.setattr(
        log_rotation,
        "_log_file_created_at",
        lambda path: datetime(2026, 7, 9, 8, 7, 6),
    )

    if app_handler._shared_handler_file_handler is not None:
        app_handler._shared_handler_file_handler.close()
    app_handler._shared_handler_file_handler = None
    app_handler._shared_handler_file_path = None

    class SoulHandler(AppHandler):
        pass

    class QQMusicHandler(AppHandler):
        pass

    config = {"logging": {"directory": str(tmp_path)}}
    controller = SimpleNamespace(config=config)

    try:
        soul = SoulHandler.__new__(SoulHandler)
        soul.config = config
        soul.controller = controller
        soul_logger = soul._setup_logger()

        music = QQMusicHandler.__new__(QQMusicHandler)
        music.config = config
        music.controller = controller
        music_logger = music._setup_logger()

        soul_logger.info("soul line")
        music_logger.info("music line")
        for handler in {id(h): h for h in soul_logger.handlers + music_logger.handlers}.values():
            handler.flush()

        active_text = old_log.read_text(encoding="utf-8")
        assert "soul line" in active_text
        assert "music line" in active_text
        assert (tmp_path / "UShareIPlay_2026-07-09_08-07-06.log").read_text(
            encoding="utf-8"
        ) == "old handler log\n"
        assert not list(tmp_path.glob("SoulHandler_*.log"))
        assert not list(tmp_path.glob("QQMusicHandler_*.log"))
    finally:
        for logger_name in ("SoulHandler", "QQMusicHandler"):
            logger = logging.getLogger(logger_name)
            for handler in logger.handlers:
                handler.close()
            logger.handlers.clear()
        if app_handler._shared_handler_file_handler is not None:
            app_handler._shared_handler_file_handler.close()
        app_handler._shared_handler_file_handler = None
        app_handler._shared_handler_file_path = None


def test_chat_logger_archives_old_active_file_and_writes_new_chat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ushareiplay.core import log_rotation
    from ushareiplay.managers import message_manager

    old_log = tmp_path / "chat.log"
    old_log.write_text("old chat\n", encoding="utf-8")
    monkeypatch.setattr(
        log_rotation,
        "_log_file_created_at",
        lambda path: datetime(2026, 7, 9, 8, 7, 6),
    )

    if message_manager.chat_logger is not None:
        for handler in message_manager.chat_logger.handlers:
            handler.close()
        message_manager.chat_logger.handlers.clear()
    message_manager.chat_logger = None

    logger = message_manager.get_chat_logger({"logging": {"directory": str(tmp_path)}})
    try:
        logger.info("new chat")
        for handler in logger.handlers:
            handler.flush()

        assert (tmp_path / "chat_2026-07-09_08-07-06.log").read_text(
            encoding="utf-8"
        ) == "old chat\n"
        assert "new chat" in old_log.read_text(encoding="utf-8")
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        message_manager.chat_logger = None
