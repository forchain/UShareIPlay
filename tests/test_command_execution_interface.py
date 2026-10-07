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


def test_intake_seam_parses_scanned_rows_and_delegates(monkeypatch):
    """Scan rows reach execution already classified, as a typed batch.

    The raw-row entry point this used to cover (`execute_chat_scan`) was removed
    in #399: it classified each screen line a second time and rebuilt a
    `MessageInfo` that dropped `silent` / `private_reply` / `quoted_text`. The
    intake seam is now the only way in, and it hands over every attribute.
    """
    from ushareiplay.core.chat_intake import build_message_batch, classify_chat_line

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()

    captured = []

    async def _fake_execute_command_messages(messages):
        captured.extend(messages)
        return len(messages)

    monkeypatch.setattr(manager, "execute_command_messages", _fake_execute_command_messages)

    lines = [
        "souler[Alice]说：:play 123",
        "souler[Bob]说：＄info",
        "not a command row",
    ]
    batch = build_message_batch([classify_chat_line(line) for line in lines])
    processed = _run(manager.execute_intake_batch(batch))

    assert processed == 2
    assert [m.content for m in captured] == [":play 123", "＄info"]
    assert [m.nickname for m in captured] == ["Alice", "Bob"]
    # The metadata the old raw-row path threw away now reaches execution.
    assert [m.private_reply for m in captured] == [False, True]


def test_process_new_messages_does_not_execute_scanned_rows_inline():
    """The scan site no longer forwards raw rows to execution (#398, #399).

    `process_new_messages` used to hand the scanned rows to
    `CommandManager.execute_chat_scan`, which classified them a second time and
    executed immediately. Commands now travel `dispatch_intake` → `MessageQueue`
    → `RuntimeQueueDrainer`, so the scan site only brings the app forward and
    does not even accept the raw rows any more (#399).

    The fake command manager below deliberately exposes no execution entry
    point at all: any attempt to execute inline would raise `AttributeError`
    rather than quietly recording a call.
    """
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    fake_command_manager = object()
    original_cmd_instance = CommandManager.instance
    try:
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = MessageManager.instance()
        manager._handler = _FakeHandler()
        manager._chat_logger = logging.getLogger("test_chat_logger_scan")
        MessageQueue.instance()
        manager.observe(["souler[Alice]说：$play 123"])

        assert _run(manager.process_new_messages()) is None
    finally:
        CommandManager.instance = original_cmd_instance
