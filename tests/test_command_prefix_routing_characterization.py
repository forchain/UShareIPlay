"""Golden routing table for every command prefix family.

This file is the regression net for #399, which deleted the command path's
second classification pass (`CommandManager.execute_chat_scan`) together with the
prefix re-derivation that used to sit in `execute_command_messages`
(`_extract_private_reply_and_normalize` / `_is_silent_command_candidate`).

The expected values below were **captured from the pre-deletion tree** by running
every prefix family through the legacy raw-row path
(`CommandManager.execute_chat_scan(["souler[Bob]说：<line>"])`) and recording the
observable routing: the screen echo, the command reply's `private_reply` /
`silent` flags, and the `MessageInfo` handed to the command. They are pinned
here as literals so the table keeps holding once the legacy path is gone.

The legacy path dropped `silent` and `quoted_text` on the `MessageInfo` it
returned — they only reached execution because the command path re-derived them
from the raw string. The intake seam carries them on the message instead, so the
table asserts the metadata survives rather than being recomputed. See
`test_prefix_routing_metadata_comes_from_intake_not_re_derivation` for the
difference this pin protects.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ushareiplay.core.chat_intake import build_message_batch, classify_chat_line
from ushareiplay.managers.command_manager import CommandManager


def _run(coro):
    return asyncio.run(coro)


class _RecordingDispatch:
    """Records what the command path actually sends, with no timestamp noise."""

    def __init__(self):
        self.screen_messages = []
        self.command_outputs = []
        self.executed = []

    def bind_handler(self, _handler):
        return self

    def configure_runtime(self, _runtime):
        return self

    def send_screen_message(self, message, silent=False):
        self.screen_messages.append((message.split("] ", 1)[1], silent))

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


def _routing_manager(monkeypatch, dispatch):
    """A CommandManager wired for real end-to-end routing assertions."""
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    monkeypatch.setattr(
        "ushareiplay.managers.command_manager.MessageDispatch.instance", lambda: dispatch
    )
    manager.configure_runtime(_FakeRuntime())
    manager._logger = logging.getLogger("test_prefix_routing")
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
        dispatch.executed.append(
            (
                message_info.content,
                message_info.silent,
                message_info.private_reply,
                message_info.quoted_text,
            )
        )
        return f"playing {command_info['parameters'][0]}"

    monkeypatch.setattr(manager, "process_command", _fake_process)
    return manager


# (case id, raw chat line, screen echo, command reply routing, executed metadata)
#
# `screen echo` is (text without timestamp, silent).
# `command reply` is (nickname, response, private_reply, silent).
# `executed` is (content, silent, private_reply, quoted_text) as seen by the
# command itself — the metadata intake attached.
PREFIX_ROUTING_CASES = [
    # `:  normal command, public screen echo, public reply
    (
        "normal_colon",
        "souler[Bob]说：:play 1",
        [("play ... @Bob", False)],
        [("Bob", "playing 1", False, False)],
        [(":play 1", False, False, "")],
    ),
    # `/  silent command: screen echo and reply both suppressed
    (
        "silent_slash",
        "souler[Bob]说：/play 2",
        [("play ... @Bob", True)],
        [("Bob", "playing 2", False, True)],
        [("/play 2", True, False, "")],
    ),
    # `：` fullwidth colon behaves exactly like `:`
    (
        "normal_fullwidth_colon",
        "souler[Bob]说：：play 3",
        [("play ... @Bob", False)],
        [("Bob", "playing 3", False, False)],
        [("：play 3", False, False, "")],
    ),
    # `／ fullwidth slash behaves exactly like `/`
    (
        "silent_fullwidth_slash",
        "souler[Bob]说：／play 4",
        [("play ... @Bob", True)],
        [("Bob", "playing 4", False, True)],
        [("／play 4", True, False, "")],
    ),
    # `$  public screen echo, private reply
    (
        "private_dollar",
        "souler[Bob]说：$play 5",
        [("play ... @Bob", False)],
        [("Bob", "playing 5", True, False)],
        [("$play 5", False, True, "")],
    ),
    # `＄ fullwidth dollar behaves exactly like `$`
    (
        "private_fullwidth_dollar",
        "souler[Bob]说：＄play 6",
        [("play ... @Bob", False)],
        [("Bob", "playing 6", True, False)],
        [("＄play 6", False, True, "")],
    ),
    # Quoted Message carrying a silent trigger: the quote is context, the
    # sender's own `/` still decides silence.
    (
        "quoted_silent",
        "souler[Bob]说：「Alice：早上好」 /play 7",
        [("play ... @Bob", True)],
        [("Bob", "playing 7", False, True)],
        [("/play 7", True, False, "Alice：早上好")],
    ),
    # Quoted Message carrying a private trigger.
    (
        "quoted_private",
        "souler[Bob]说：「Alice：早上好」 $play 8",
        [("play ... @Bob", False)],
        [("Bob", "playing 8", True, False)],
        [("$play 8", False, True, "Alice：早上好")],
    ),
    # Quoted Message carrying a normal trigger.
    (
        "quoted_normal",
        "souler[Bob]说：「Alice：早上好」 :play 9",
        [("play ... @Bob", False)],
        [("Bob", "playing 9", False, False)],
        [(":play 9", False, False, "Alice：早上好")],
    ),
    # A leading space does not change which family the prefix belongs to.
    (
        "leading_space_normal",
        "souler[Bob]说： :play 10",
        [("play ... @Bob", False)],
        [("Bob", "playing 10", False, False)],
        [(":play 10", False, False, "")],
    ),
    (
        "leading_space_silent",
        "souler[Bob]说： /play 11",
        [("play ... @Bob", True)],
        [("Bob", "playing 11", False, True)],
        [("/play 11", True, False, "")],
    ),
    # `$` then `/`: private reply wins for routing, the `/` behind it still
    # silences the reply. This is the one combination the old command path got
    # right by re-deriving `is_silent_prefix` from the raw string while intake
    # recorded `silent=False`; the screen/reply routing below is what the old
    # path produced and is unchanged. The `executed` tuple differs on purpose:
    # `message_info.silent` used to be a stale `False` that a local variable
    # overrode, and is now the truthful `True` intake attached.
    (
        "private_then_silent",
        "souler[Bob]说：$/play 12",
        [("play ... @Bob", True)],
        [("Bob", "playing 12", True, True)],
        [("$/play 12", True, True, "")],
    ),
    # A trigger with nothing behind it is not a command.
    ("trigger_only_colon", "souler[Bob]说：:", [], [], []),
    # Plain chat is never a command.
    ("plain_chat", "souler[Bob]说：大家好", [], [], []),
]


@pytest.mark.parametrize(
    "line,expected_screen,expected_output,expected_executed",
    [case[1:] for case in PREFIX_ROUTING_CASES],
    ids=[case[0] for case in PREFIX_ROUTING_CASES],
)
def test_prefix_family_routing_is_pinned(
    monkeypatch, line, expected_screen, expected_output, expected_executed
):
    """Every prefix family routes exactly as it did before #399 removed the
    second classification pass."""
    dispatch = _RecordingDispatch()
    manager = _routing_manager(monkeypatch, dispatch)

    batch = build_message_batch([classify_chat_line(line)], source="screen")
    processed = _run(manager.execute_intake_batch(batch))

    assert dispatch.screen_messages == expected_screen
    assert dispatch.command_outputs == expected_output
    assert dispatch.executed == expected_executed
    assert processed == len(expected_output)


@pytest.mark.parametrize(
    "line,expected_screen,expected_output,expected_executed",
    [case[1:] for case in PREFIX_ROUTING_CASES],
    ids=[case[0] for case in PREFIX_ROUTING_CASES],
)
def test_prefix_family_routing_survives_the_queue_drain(
    monkeypatch, line, expected_screen, expected_output, expected_executed
):
    """The same table holds through the production path: intake → queue → drain.

    Screen commands are executed by `RuntimeQueueDrainer`, not by the scan site,
    so this pins the routing at the place it actually happens in production.
    """
    from ushareiplay.core.message_queue import MessageQueue

    dispatch = _RecordingDispatch()
    manager = _routing_manager(monkeypatch, dispatch)

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    batch = build_message_batch([classify_chat_line(line)], source="screen")
    for command in batch.commands:
        _run(queue.put_message(command))

    sent = []
    _run(
        manager.execute_runtime_queue_messages(
            list(_run(queue.get_all_messages()).values()),
            send_screen_message=sent.append,
        )
    )

    assert sent == []
    assert dispatch.screen_messages == expected_screen
    assert dispatch.command_outputs == expected_output
    # `quoted_text` is consumed by nothing in `src/`, and the drainer rebuilds the
    # message through the queue grammar, which does not carry the quote through.
    # Routing — the part users see — is identical; only this inert field differs.
    assert [(c, s, p) for c, s, p, _q in dispatch.executed] == [
        (c, s, p) for c, s, p, _q in expected_executed
    ]


def test_command_path_no_longer_re_evaluates_prefixes(monkeypatch):
    """The command path holds no prefix-semantics helpers and classifies nothing.

    #399 removed the second classification pass. What is left on `CommandManager`
    is the trigger strip needed for parser lookup — the config stores prefixes
    without the trigger (`play`, not `:play`) — plus the intake seam, which
    consumes an already-classified batch. The chat-intake symbols that carried
    the prefix *semantics* are no longer imported here at all.
    """
    from ushareiplay.managers import command_manager as command_manager_module

    for removed in (
        "execute_chat_scan",
        "handle_message_commands",
        "_normalize_command_candidate",
        "_extract_private_reply_and_normalize",
        "_is_silent_command_candidate",
    ):
        assert not hasattr(command_manager_module.CommandManager, removed), removed

    # Chat Intake owns the patterns; CommandManager imports none of the
    # classification surface.
    for not_owned in (
        "classify_chat_line",
        "classify_banner_line",
        "is_silent_prefix",
        "is_private_reply_prefix",
        "ChatIntakeKind",
        "QUEUE_COMMAND_PREFIX_CHARS",
    ):
        assert not hasattr(command_manager_module, not_owned), not_owned


def test_prefix_routing_metadata_comes_from_intake_not_re_derivation(monkeypatch):
    """`silent` / `private_reply` / `quoted_text` are read off the message.

    This is the property #399 bought: the command path no longer re-evaluates
    the prefix against raw text, so the metadata it sees is exactly what intake
    attached — including the quote, which no prefix re-derivation could recover.
    """
    dispatch = _RecordingDispatch()
    manager = _routing_manager(monkeypatch, dispatch)

    batch = build_message_batch(
        [
            classify_chat_line("souler[Bob]说：「Alice：早上好」 $play 8"),
            classify_chat_line("souler[Bob]说：/play 2"),
        ],
        source="screen",
    )
    _run(manager.execute_intake_batch(batch))

    assert dispatch.executed == [
        ("$play 8", False, True, "Alice：早上好"),
        ("/play 2", True, False, ""),
    ]
