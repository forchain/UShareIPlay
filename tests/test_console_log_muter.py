import logging
import queue
from unittest.mock import MagicMock
import pytest

from ushareiplay.core.console_log_muter import ConsoleLogMuter
from ushareiplay.core.app_controller import AppController


def test_console_log_muter_filter_record():
    muter = ConsoleLogMuter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="test message",
        args=(),
        exc_info=None,
    )

    assert muter.filter(record) is True

    muter.mute()
    assert muter.is_muted() is True
    assert muter.filter(record) is False

    muter.unmute()
    assert muter.is_muted() is False
    assert muter.filter(record) is True


def test_console_log_muter_context():
    muter = ConsoleLogMuter()
    assert muter.is_muted() is False

    with muter.paused():
        assert muter.is_muted() is True

    assert muter.is_muted() is False


def test_app_handler_console_handler_has_muter_filter(tmp_path):
    from types import SimpleNamespace
    from ushareiplay.handlers.soul_handler import SoulHandler

    config = {
        "logging": {"directory": str(tmp_path)},
        "soul": {},
    }
    controller = SimpleNamespace(config=config)

    soul = SoulHandler.__new__(SoulHandler)
    soul.config = config
    soul.controller = controller
    logger = soul._setup_logger()

    # Find console StreamHandler
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
    assert len(stream_handlers) == 1
    stream_handler = stream_handlers[0]

    # Verify ConsoleLogMuter filter is in filters
    muter_filters = [f for f in stream_handler.filters if isinstance(f, ConsoleLogMuter)]
    assert len(muter_filters) == 1


def test_file_log_continues_when_console_is_muted(tmp_path):
    from types import SimpleNamespace
    from ushareiplay.handlers.soul_handler import SoulHandler

    config = {
        "logging": {"directory": str(tmp_path)},
        "soul": {},
    }
    controller = SimpleNamespace(config=config)

    soul = SoulHandler.__new__(SoulHandler)
    soul.config = config
    soul.controller = controller
    logger = soul._setup_logger()

    muter = ConsoleLogMuter.get_instance()
    muter.mute()
    try:
        logger.info("message while muted")
        for h in logger.handlers:
            h.flush()
        
        log_file = tmp_path / "UShareIPlay.log"
        assert log_file.exists()
        assert "message while muted" in log_file.read_text(encoding="utf-8")
    finally:
        muter.unmute()
        for h in logger.handlers:
            h.close()


def test_console_input_flow_empty_enter_then_command(monkeypatch):
    """
    When user presses Enter (empty string), console log is muted,
    and prompt is shown for command input until command is entered.
    """
    muter = ConsoleLogMuter.get_instance()
    muter.unmute()

    controller = AppController.__new__(AppController)
    controller.is_running = True
    controller.in_console_mode = False
    controller.input_queue = queue.Queue()
    controller.logger = MagicMock()

    inputs = iter(["", "!timer"])
    prompts = []

    def fake_input(prompt=""):
        prompts.append((prompt, muter.is_muted()))
        try:
            return next(inputs)
        except StopIteration:
            controller.is_running = False
            return ""

    monkeypatch.setattr("builtins.input", fake_input)

    controller._console_input()

    assert len(prompts) >= 2
    assert prompts[0][1] is False  # Before enter, not muted
    assert prompts[1][1] is True   # After enter, muted while reading command
    assert muter.is_muted() is False  # After command entered, unmutes

    queued_items = []
    while not controller.input_queue.empty():
        queued_items.append(controller.input_queue.get())
    assert ("!timer", "console") in queued_items

def test_console_input_flow_direct_command_without_enter(monkeypatch):
    """
    If user types a command directly when not muted, it is queued directly.
    """
    muter = ConsoleLogMuter.get_instance()
    muter.unmute()

    controller = AppController.__new__(AppController)
    controller.is_running = True
    controller.in_console_mode = False
    controller.input_queue = queue.Queue()
    controller.logger = MagicMock()

    inputs = iter(["!timer"])

    def fake_input(prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            controller.is_running = False
            return ""

    monkeypatch.setattr("builtins.input", fake_input)
    controller._console_input()

    assert muter.is_muted() is False
    queued_items = []
    while not controller.input_queue.empty():
        queued_items.append(controller.input_queue.get())
    assert ("!timer", "console") in queued_items


def test_console_input_flow_cancel_with_empty_enter(monkeypatch):
    """
    If user presses Enter to mute, then presses Enter again without command,
    it exits command mode and un-mutes logs.
    """
    muter = ConsoleLogMuter.get_instance()
    muter.unmute()

    controller = AppController.__new__(AppController)
    controller.is_running = True
    controller.in_console_mode = False
    controller.input_queue = queue.Queue()
    controller.logger = MagicMock()

    inputs = iter(["", ""])

    def fake_input(prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            controller.is_running = False
            return ""

    monkeypatch.setattr("builtins.input", fake_input)
    controller._console_input()

    assert muter.is_muted() is False
