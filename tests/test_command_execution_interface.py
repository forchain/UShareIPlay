import asyncio
import logging
from collections import deque

from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.models.message_info import MessageInfo


def _run(coro):
    return asyncio.run(coro)


class _FakeHandler:
    def __init__(self):
        self.sent = []
        self.logger = logging.getLogger("test_command_execution_interface")
        self.config = {"logging": {"directory": "logs"}}

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


def test_process_new_messages_uses_command_execution_chat_scan(monkeypatch):
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeCommandManager:
        def __init__(self):
            self.rows = None

        async def execute_chat_scan(self, rows):
            self.rows = list(rows)
            return [MessageInfo("$play 123", "Alice")]

    fake_command_manager = _FakeCommandManager()
    monkeypatch.setattr(CommandManager, "_instance", fake_command_manager, raising=False)
    manager = object.__new__(MessageManager)
    manager._handler = _FakeHandler()
    manager._chat_logger = logging.getLogger("test_chat_logger_scan")
    manager.recent_chats = deque(maxlen=3)
    manager.latest_chats = deque(maxlen=3)
    manager.latest_chats.append("souler[Alice]说：$play 123")

    messages = _run(manager.process_new_messages())

    assert fake_command_manager.rows == ["souler[Alice]说：$play 123"]
    assert [m.content for m in messages] == ["$play 123"]
