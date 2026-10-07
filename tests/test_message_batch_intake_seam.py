"""Intake seam: a typed `MessageBatch` carries command metadata across the boundary.

Chat Intake already computes `silent` / `private_reply` / `quoted_text` /
`sleep_exempt` while classifying a line. These tests pin that this metadata
survives the trip from `ChatIntakeResult` to the `MessageInfo` that command
execution consumes, and that the seam needs only one classification pass.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

from ushareiplay.core.chat_intake import (
    ChatIntakeKind,
    MessageBatch,
    build_message_batch,
    classify_chat_line,
    expand_queue_text,
)
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.models.message_info import MessageInfo


def _run(coro):
    return asyncio.run(coro)


def _without_timestamp(screen_message: str) -> str:
    """Drop the `[HH:MM:SS] ` stamp so two runs can be compared."""
    return screen_message.split("] ", 1)[1]


def test_message_batch_preserves_every_command_attribute():
    """A quoted private command keeps all four attributes, including quoted_text."""
    result = classify_chat_line('souler[Alice]说：「Bob：你好」 $play 123')

    assert result.kind == ChatIntakeKind.COMMAND
    assert result.private_reply is True
    assert result.silent is False
    assert result.quoted_text == "Bob：你好"

    batch = build_message_batch([result])

    assert isinstance(batch, MessageBatch)
    assert batch.items == (result,)
    assert len(batch.commands) == 1

    command = batch.commands[0]
    assert command.content == "$play 123"
    assert command.nickname == "Alice"
    assert command.silent is False
    assert command.private_reply is True
    assert command.quoted_text == "Bob：你好"


def test_message_batch_preserves_sleep_exempt_when_intake_sets_it():
    """`sleep_exempt` is threaded through, not hardcoded to False.

    Screen chat is never sleep-exempt (`classify_chat_line` has no such
    signal), so this uses the queue grammar — the one path where intake does
    compute it — to prove the attribute actually crosses the seam.
    """
    results = expand_queue_text(";$info", "Alice", sleep_exempt=True)

    batch = build_message_batch(results)

    assert [c.content for c in batch.commands] == ["$info"]
    assert batch.commands[0].sleep_exempt is True
    assert batch.commands[0].private_reply is True


def test_message_batch_keeps_non_command_items_without_promoting_them():
    """The batch carries every classified item, but only commands become messages."""
    results = [
        classify_chat_line("souler[Alice]说：/play 123"),
        classify_chat_line("souler[Bob]说：大家好"),
    ]

    batch = build_message_batch(results)

    assert [item.kind for item in batch.items] == [
        ChatIntakeKind.COMMAND,
        ChatIntakeKind.PLAIN_CHAT,
    ]
    assert [c.content for c in batch.commands] == ["/play 123"]
    assert batch.commands[0].silent is True


def test_message_info_keeps_working_for_positional_construction():
    """`quoted_text` is appended, so the two-positional-arg form still works."""
    message = MessageInfo("/play 123", "Bob")

    assert message.content == "/play 123"
    assert message.nickname == "Bob"
    assert message.quoted_text == ""


def test_screen_scan_builds_metadata_complete_batch(chat_window):
    """The scan site attaches intake metadata; it no longer rebuilds bare messages."""
    batch = _run(
        chat_window.manager.dispatch_intake(
            [
                'souler[Alice]说：「Bob：你好」 $play 123',
                "souler[Bob]说：/play 9",
            ],
            room_owner="群主",
        )
    )

    assert isinstance(batch, MessageBatch)
    assert [item.kind for item in batch.items] == [
        ChatIntakeKind.COMMAND,
        ChatIntakeKind.COMMAND,
    ]
    assert [c.content for c in batch.commands] == ["$play 123", "/play 9"]
    assert [c.private_reply for c in batch.commands] == [True, False]
    assert [c.silent for c in batch.commands] == [False, True]
    assert [c.quoted_text for c in batch.commands] == ["Bob：你好", ""]


def test_screen_scan_classifies_gifts_with_room_owner(chat_window, monkeypatch):
    """The batch is built where `room_owner` is known, so gifts classify correctly.

    A gift is only `GIFT_RECEIVE` when the receiver is the room owner. Building
    the batch anywhere without that context would classify it as plain chat.
    """
    monkeypatch.setattr(
        chat_window.manager,
        "handle_gift_receive",
        _noop_coro,
    )

    batch = _run(
        chat_window.manager.dispatch_intake(
            ["souler[Alice] 送给 群主 一束花"],
            room_owner="群主",
        )
    )

    assert [item.kind for item in batch.items] == [ChatIntakeKind.GIFT_RECEIVE]
    assert batch.commands == ()


def test_dispatch_return_value_keeps_command_metadata(chat_window):
    """`dispatch()` still returns a list, but its messages are no longer bare."""
    commands = _run(
        chat_window.manager.dispatch(["souler[Alice]说：/play 123"], room_owner="群主")
    )

    assert [(c.content, c.nickname) for c in commands] == [("/play 123", "Alice")]
    assert commands[0].silent is True


async def _noop_coro(*args, **kwargs):
    return None


# --------------------------------------------------------------------------
# Command execution side of the seam
# --------------------------------------------------------------------------


class _RecordingDispatch:
    def __init__(self):
        self.screen_messages = []
        self.command_outputs = []

    def bind_handler(self, _handler):
        return self

    def send_screen_message(self, message, silent=False):
        self.screen_messages.append((_without_timestamp(message), silent))

    def send_for_message_info(self, message_info, response, silent=False):
        self.command_outputs.append(
            (message_info.nickname, response, message_info.private_reply, silent)
        )
        return True


class _FakeObserver:
    def emit(self, name, **kwargs):
        return None


class _FakeRuntime:
    def __init__(self):
        self.controller = SimpleNamespace(
            obs=_FakeObserver(), soul_handler=object(), music_handler=object()
        )

    @asynccontextmanager
    async def ui_session(self, reason):
        yield


def _routing_manager(monkeypatch):
    """A CommandManager wired for real end-to-end routing assertions."""
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager.configure_runtime(_FakeRuntime())
    manager._logger = logging.getLogger("test_message_batch_seam")
    manager._handler = SimpleNamespace(config={"system_users": ["Console"]})
    manager.initialize_parser(
        [
            {
                "prefix": "play",
                "level": 1,
                "response_template": "{song}",
                "error_template": "{error}",
            }
        ]
    )
    monkeypatch.setattr(manager, "get_command", lambda _cmd: object())

    async def _fake_process(_command, message_info, command_info):
        return f"playing {command_info['parameters'][0]}"

    monkeypatch.setattr(manager, "process_command", _fake_process)
    return manager


def test_intake_seam_does_not_classify_raw_lines_again(monkeypatch):
    """The seam consumes the batch as-is: no re-classification, no rebuild.

    Before #399 this counted calls to `CommandManager`'s own reference to
    `classify_chat_line`. That reference is gone now — `CommandManager` no
    longer imports the classification surface at all, which
    `test_command_prefix_routing_characterization.py` asserts directly. What is
    left to pin here is that the very objects intake built are the ones executed,
    so nothing between the seam and execution can rewrite the metadata.
    """
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()

    captured = []

    async def _fake_execute_command_messages(messages):
        captured.extend(messages)
        return len(messages)

    monkeypatch.setattr(manager, "execute_command_messages", _fake_execute_command_messages)

    batch = build_message_batch([classify_chat_line("souler[Bob]说：/play 123")])
    _run(manager.execute_intake_batch(batch))

    assert len(captured) == 1
    assert captured[0] is batch.commands[0]  # same object, not a rebuild
    assert captured[0].content == "/play 123"
    assert captured[0].silent is True


def test_intake_seam_routes_a_silent_and_a_private_command(monkeypatch):
    """`/play` stays public-but-silent; `$play` replies privately."""
    manager = _routing_manager(monkeypatch)
    dispatch = _RecordingDispatch()
    monkeypatch.setattr(
        "ushareiplay.managers.command_manager.MessageDispatch.instance", lambda: dispatch
    )

    batch = build_message_batch(
        [
            classify_chat_line("souler[Bob]说：/play 123"),
            classify_chat_line("souler[Alice]说：$play 456"),
        ]
    )

    processed = _run(manager.execute_intake_batch(batch))

    assert processed == 2
    assert dispatch.screen_messages == [
        ("play ... @Bob", True),
        ("play ... @Alice", False),
    ]
    assert dispatch.command_outputs == [
        ("Bob", "playing 123", False, True),
        ("Alice", "playing 456", True, False),
    ]


def test_intake_seam_routes_every_prefix_family_as_the_legacy_scan_did(monkeypatch):
    """Golden routing for the seam, captured from the raw-row path before #399.

    This used to compare the batch against `CommandManager.execute_chat_scan`
    live, so it could only prove the two agreed while the legacy path existed.
    #399 deleted that path; the expected routing is now pinned outright, using
    the values the legacy path produced on the pre-deletion tree. The full table
    — every prefix family, plus quoted and edge-case variants — lives in
    `test_command_prefix_routing_characterization.py`; this keeps the guard that
    the seam itself routes both a silent and a private command correctly.
    """
    manager = _routing_manager(monkeypatch)
    dispatch = _RecordingDispatch()
    monkeypatch.setattr(
        "ushareiplay.managers.command_manager.MessageDispatch.instance",
        lambda: dispatch,
    )

    lines = [
        "souler[Bob]说：/play 123",
        "souler[Alice]说：$play 456",
    ]
    batch = build_message_batch([classify_chat_line(line) for line in lines])
    processed = _run(manager.execute_intake_batch(batch))

    assert processed == 2
    assert dispatch.screen_messages == [
        ("play ... @Bob", True),
        ("play ... @Alice", False),
    ]
    assert dispatch.command_outputs == [
        ("Bob", "playing 123", False, True),
        ("Alice", "playing 456", True, False),
    ]


def test_intake_seam_ignores_a_batch_without_commands():
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()

    assert _run(manager.execute_intake_batch(MessageBatch())) == 0


def test_scanned_chat_flows_to_execution_in_a_single_classification_pass(
    chat_window, monkeypatch
):
    """Scan → batch → execution, with each line classified exactly once."""
    manager = _routing_manager(monkeypatch)
    dispatch = _RecordingDispatch()
    monkeypatch.setattr(
        "ushareiplay.managers.command_manager.MessageDispatch.instance",
        lambda: dispatch,
    )

    from ushareiplay.managers import message_manager as message_manager_module

    calls = []
    real_classify = message_manager_module.classify_chat_line

    def _counting_classify(raw, room_owner=None):
        calls.append(raw)
        return real_classify(raw, room_owner=room_owner)

    monkeypatch.setattr(message_manager_module, "classify_chat_line", _counting_classify)

    lines = [
        'souler[Bob]说：「Alice：早上好」 /play 123',
        "souler[Alice]说：$play 456",
    ]
    batch = _run(chat_window.manager.dispatch_intake(lines, room_owner="群主"))

    assert calls == lines
    assert [c.quoted_text for c in batch.commands] == ["Alice：早上好", ""]

    processed = _run(manager.execute_intake_batch(batch))

    assert calls == lines  # the seam did not classify anything again
    assert processed == 2
    assert dispatch.screen_messages == [
        ("play ... @Bob", True),
        ("play ... @Alice", False),
    ]
    assert dispatch.command_outputs == [
        ("Bob", "playing 123", False, True),
        ("Alice", "playing 456", True, False),
    ]
