import asyncio
import logging
from collections import deque
from types import SimpleNamespace

from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.models.message_info import MessageInfo


def _run(coro):
    return asyncio.run(coro)


class _FakeHandler:
    def __init__(self):
        self.sent = []
        self.logger = logging.getLogger("test_command_execution_interface")
        self.config = {"logging": {"directory": "logs"}}
        self.key_actions = SimpleNamespace(switch_to_app=lambda: True)

    def send_message(self, message):
        self.sent.append(message)

    def switch_to_app(self):
        return True


def test_execute_runtime_queue_routes_plain_and_command_parts(monkeypatch):
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()

    captured = []

    async def _fake_execute_command_messages(messages):
        captured.extend(messages)
        return len(messages)

    monkeypatch.setattr(manager, "execute_command_messages", _fake_execute_command_messages)

    handler = _FakeHandler()
    queue_messages = [
        MessageInfo(content="hello {user_name};:timer list", nickname="Alice"),
    ]

    command_count = _run(
        manager.execute_runtime_queue_messages(queue_messages, send_screen_message=handler.send_message)
    )

    assert command_count == 1
    assert handler.sent == ["hello Alice"]
    assert [m.content for m in captured] == [":timer list"]
    assert [m.nickname for m in captured] == ["Alice"]


def test_execute_runtime_queue_preserves_silent_routing(monkeypatch):
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()

    captured = []

    async def _fake_execute_command_messages(messages):
        captured.extend(messages)
        return len(messages)

    monkeypatch.setattr(manager, "execute_command_messages", _fake_execute_command_messages)

    handler = _FakeHandler()
    queue_messages = [
        MessageInfo(content="hello;/timer list", nickname="Alice", silent=True),
    ]

    command_count = _run(
        manager.execute_runtime_queue_messages(queue_messages, send_screen_message=handler.send_message)
    )

    assert command_count == 1
    assert handler.sent == []
    assert [m.content for m in captured] == ["/timer list"]
    assert [m.silent for m in captured] == [True]


def test_execute_runtime_queue_returns_routed_count_not_execution_count(monkeypatch):
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()

    captured = []

    async def _fake_execute_command_messages(messages):
        captured.extend(messages)
        return 0

    monkeypatch.setattr(manager, "execute_command_messages", _fake_execute_command_messages)

    command_count = _run(
        manager.execute_runtime_queue_messages(
            [MessageInfo(content=":unknown", nickname="Alice")]
        )
    )

    assert command_count == 1
    assert [m.content for m in captured] == [":unknown"]


def test_execute_chat_scan_parses_scanned_rows_and_delegates(monkeypatch):
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()

    captured = []

    async def _fake_execute_command_messages(messages):
        captured.extend(messages)
        return len(messages)

    monkeypatch.setattr(manager, "execute_command_messages", _fake_execute_command_messages)

    messages = _run(
        manager.execute_chat_scan(
            [
                "souler[Alice]说：:play 123",
                "souler[Bob]说：＄info",
                "not a command row",
            ]
        )
    )

    assert [m.content for m in messages] == [":play 123", "＄info"]
    assert [m.nickname for m in messages] == ["Alice", "Bob"]
    assert [m.content for m in captured] == [":play 123", "＄info"]
    assert [m.nickname for m in captured] == ["Alice", "Bob"]


def test_process_live_batch_routes_commands_through_execute_chat_scan(monkeypatch):
    """process_live_batch is the Command Execution seam.

    Given an empty cursor and a fresh visible batch, a valid command must
    travel all the way through: Chat Intake classification -> execute_chat_scan
    routing -> MessageInfo delivered to execute_command_messages.
    """
    from ushareiplay.managers.command_manager import CommandManager

    captured = []

    async def _fake_execute_command_messages(messages):
        captured.extend(messages)
        return len(messages)

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager._handler = _FakeHandler()
    manager._chat_logger = logging.getLogger("test_chat_logger_scan")
    manager._recent_chats = deque(maxlen=3)
    manager._latest_chats = deque(maxlen=3)
    monkeypatch.setattr(manager, "execute_command_messages", _fake_execute_command_messages)
    # Skip missed-history side-effects during the smoke test.
    async def _no_recover():
        return None
    monkeypatch.setattr(manager, "recover_missed_history", _no_recover)

    result = _run(
        manager.process_live_batch(
            ["souler[Alice]说：$play 123", "souler[Bob]说：hello world"]
        )
    )

    assert [m.content for m in captured] == ["$play 123"]
    assert [m.nickname for m in captured] == ["Alice"]
    assert result == {"missed": False, "command_count": 1}
    assert list(manager._recent_chats) == [
        "souler[Alice]说：$play 123",
        "souler[Bob]说：hello world",
    ]


def test_process_live_batch_idle_batch_runs_update_path(monkeypatch):
    """When the fresh batch has no command, the idle outcome ticks."""
    from ushareiplay.managers.command_manager import CommandManager

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager._handler = _FakeHandler()
    manager._chat_logger = logging.getLogger("test_chat_logger_idle")
    manager._recent_chats = deque(maxlen=3)
    manager._latest_chats = deque(maxlen=3)

    update_calls = {"count": 0}
    playback_calls = {"count": 0}

    def _update():
        update_calls["count"] += 1

    class _FakePlayback:
        def update_playback_info_cache(self):
            playback_calls["count"] += 1

    monkeypatch.setattr(manager, "update_commands", _update)
    from ushareiplay.state import playback_broadcaster
    monkeypatch.setattr(
        playback_broadcaster.PlaybackBroadcaster,
        "instance",
        classmethod(lambda cls: _FakePlayback()),
        raising=False,
    )

    result = _run(manager.process_live_batch(["souler[Alice]说：hello world"]))

    assert update_calls["count"] == 1
    assert playback_calls["count"] == 1
    assert result["missed"] is False
    assert result["command_count"] == 0
