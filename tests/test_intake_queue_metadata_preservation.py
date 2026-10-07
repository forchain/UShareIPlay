"""The runtime queue must not re-apply queue grammar to intake-classified messages.

`MessageQueue` carries two producers with two different grammars:

- **Intake producers** (screen scan, backfill) enqueue messages that
  `classify_chat_line` / `build_message_batch` already classified, with every
  piece of metadata attached.
- **Queue-grammar producers** (timers, gift thanks, console/agent input) enqueue
  raw text where `;` splitting and `{user_name}` substitution are intended.

`CommandManager.execute_runtime_queue_messages` used to run `route_queue_text`
over *both*. That truncated a screen command at the first `;` and rebuilt a
`MessageInfo` that dropped `quoted_text`.

Every test here drives the real `MessageQueue`, the real `RuntimeQueueDrainer`
and the real `route_queue_text`, so the grammar decision itself is under test —
not a stub. The e2e test `test_runtime_queue_pipeline.py::
test_monitoring_loop_executes_a_screen_command_on_the_tick_after_it_is_scanned`
stubs `execute_runtime_queue_messages`, which is how the data loss survived a
green suite.
"""

import asyncio
import logging

from ushareiplay.core.chat_intake import build_message_batch, classify_chat_line
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.runtime_services import RuntimeQueueDrainer
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.message_manager import MessageManager
from ushareiplay.models.message_info import MessageInfo


def _run(coro):
    return asyncio.run(coro)


def _with_ui_components(handler):
    handler.key_actions = handler
    handler.gesture_handler = handler
    handler.element_finder = handler
    return handler


class _FakeSoulHandler:
    def __init__(self):
        self.sent = []
        self.logger = logging.getLogger("test_intake_queue_preservation")
        self.config = {"logging": {"directory": "logs"}}
        self.controller = None

    def send_message(self, message):
        self.sent.append(message)

    def switch_to_app(self):
        return True


def _scan_lines(*lines, from_backfill=False):
    """Run raw chat lines through the real scan site, leaving them in the queue.

    The queue is deliberately NOT drained here: draining is what these tests are
    about, and a helper that consumed the queue would let them pass vacuously.
    Returns the `MessageBatch` intake produced, so a test can assert on the
    intake side without stealing the messages the drainer is supposed to find.
    """
    manager = MessageManager.instance()
    manager._handler = _with_ui_components(_FakeSoulHandler())
    manager._chat_logger = logging.getLogger("test_chat_logger_intake_queue")
    queue = MessageQueue.instance()
    _run(queue.clear_queue())

    return _run(
        manager.dispatch_intake(
            list(lines), room_owner="群主", from_backfill=from_backfill
        )
    )


def _real_command_manager():
    """A real `CommandManager`, with execution captured at the execution seam."""
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager._logger = logging.getLogger("test_intake_queue_command_manager")

    captured = []

    async def _capture(messages):
        captured.extend(messages)
        return len(messages)

    manager.execute_command_messages = _capture
    return manager, captured


def _drain(command_manager, handler=None):
    handler = handler or _FakeSoulHandler()
    drainer = RuntimeQueueDrainer(
        handler=handler,
        command_manager=command_manager,
        send_screen_message=handler.send_message,
        logger=handler.logger,
    )
    drained, command_count = _run(drainer.drain())
    return drained, command_count, handler


def test_screen_command_containing_semicolon_reaches_execution_whole():
    """HARD-3: `:play a;b` is ONE command, and nothing leaks to the screen.

    The queue grammar splits on `;` because timers legitimately send
    `:play a;:mode random` as one message. A person typing `:play a;b` in chat
    meant one command, and `b` must not be posted to the room as chat.
    """
    _scan_lines("souler[Bob]说：:play a;b")

    manager, captured = _real_command_manager()
    _drain(manager)

    assert [m.content for m in captured] == [":play a;b"]
    assert [m.nickname for m in captured] == ["Bob"]


def test_backfilled_command_containing_semicolon_reaches_execution_whole():
    """The backfill path shares the screen path, so it shares the fix."""
    _scan_lines("souler[Bob]说：/play a;b", from_backfill=True)

    manager, captured = _real_command_manager()
    _drain(manager)

    assert [m.content for m in captured] == ["/play a;b"]


def test_quoted_text_survives_intake_queue_drain_to_execution():
    """HARD-2: the quoted message the sender replied to reaches the command.

    `route_queue_text` rebuilt `MessageInfo` from scratch and omitted
    `quoted_text` entirely, so the reply context was silently dropped at the
    drain.
    """
    batch = _scan_lines("souler[Bob]说：「Alice：hi」 :play x")
    assert [m.quoted_text for m in batch.commands] == ["Alice：hi"], "intake must attach the quote"

    manager, captured = _real_command_manager()
    _drain(manager)

    assert [m.quoted_text for m in captured] == ["Alice：hi"]


def test_intake_metadata_reaches_execution_without_re_derivation():
    """HARD-2: silent / private_reply travel as metadata, not re-derived from text.

    `private_reply` used to survive the drain only by coincidence — the prefix
    character was still in the rebuilt content, so the same answer came out for
    the wrong reason.
    """
    _scan_lines("souler[Bob]说：$info", "souler[Carol]说：/mode random")

    manager, captured = _real_command_manager()
    _drain(manager)

    assert [m.private_reply for m in captured] == [True, False]
    assert [m.silent for m in captured] == [False, True]
    assert [m.content for m in captured] == ["$info", "/mode random"]


def test_intake_messages_are_never_classified_a_second_time(monkeypatch):
    """HARD-4: the drainer performs zero secondary classification for intake messages.

    `expand_queue_text` is the queue-grammar classifier. Counting its calls pins
    #399's "zero secondary classification" on the live path instead of on a
    test-only entry point.
    """
    from ushareiplay.core import runtime_services

    calls = []
    real_expand = runtime_services.expand_queue_text

    def _counting_expand(*args, **kwargs):
        calls.append(args[0] if args else None)
        return real_expand(*args, **kwargs)

    monkeypatch.setattr(runtime_services, "expand_queue_text", _counting_expand)

    _scan_lines("souler[Bob]说：:play 晴天")
    manager, _captured = _real_command_manager()
    _drain(manager)

    assert calls == [], "intake already classified; the queue must not classify again"


def test_intake_commands_reach_the_intake_seam_on_the_live_path(monkeypatch):
    """HARD-1: the intake seam runs in production, not only in tests.

    `execute_intake_batch` is the seam #396 asks for. If the drainer routes
    intake messages around it, the seam is dead code wearing a seam's name.
    """
    manager, captured = _real_command_manager()

    seen = []
    real_intake_batch = manager.execute_intake_batch

    async def _spy(batch):
        seen.append(batch)
        return await real_intake_batch(batch)

    manager.execute_intake_batch = _spy

    _scan_lines("souler[Bob]说：:play 晴天")
    _drain(manager)

    assert len(seen) == 1
    assert [m.content for m in seen[0].commands] == [":play 晴天"]
    assert [m.content for m in captured] == [":play 晴天"]


def test_queue_grammar_producers_still_split_and_substitute():
    """Timer-shaped messages keep `;` splitting and `{user_name}` substitution.

    This is the counterweight to the bypass above: the queue grammar belongs to
    the raw-text producers, and must not regress with them.
    """
    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(
        queue.put_message(
            MessageInfo(content="hi {user_name};:play 晴天", nickname="Alice")
        )
    )

    manager, captured = _real_command_manager()
    _drained, command_count, handler = _drain(manager)

    assert command_count == 1
    assert [m.content for m in captured] == [":play 晴天"]
    assert [m.nickname for m in captured] == ["Alice"]
    assert handler.sent == ["hi Alice"]


def test_queue_grammar_producers_still_split_silent_and_private_parts():
    """The whole prefix matrix still resolves for raw-text producers."""
    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(
        queue.put_message(
            MessageInfo(
                content="hello;/mode random;$info",
                nickname="Alice",
                sleep_exempt=True,
            )
        )
    )

    manager, captured = _real_command_manager()
    _drained, command_count, handler = _drain(manager)

    assert command_count == 2
    assert [m.content for m in captured] == ["/mode random", "$info"]
    assert [m.silent for m in captured] == [True, False]
    assert [m.private_reply for m in captured] == [False, True]
    assert [m.sleep_exempt for m in captured] == [True, True]
    assert handler.sent == ["hello"]


def test_intake_and_queue_producers_coexist_in_one_drain():
    """A single tick can carry both grammars; each keeps its own rules.

    Order is grouped by grammar (queue-grammar first, then intake), not global
    FIFO — commands are independent, so the grouping carries no semantics. What
    matters here is that neither grammar is applied to the other's producer.
    """
    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _scan_lines("souler[Bob]说：:play a;b")
    _run(queue.put_message(MessageInfo(content="hi {user_name};:timer list", nickname="Timer")))

    manager, captured = _real_command_manager()
    _drained, command_count, handler = _drain(manager)

    assert command_count == 2
    # Queue-grammar entry splits and substitutes; the screen entry does not.
    assert sorted(m.content for m in captured) == [":play a;b", ":timer list"]
    assert [m.content for m in captured] == [":timer list", ":play a;b"]
    assert [m.nickname for m in captured] == ["Timer", "Bob"]
    assert handler.sent == ["hi Timer"]


def test_queued_screen_command_carries_its_source_provenance():
    """JUDG-1: `MessageInfo.source` is populated, not a log-local duplicate."""
    batch = _scan_lines("souler[Bob]说：:play 晴天")
    assert [m.source for m in batch.commands] == ["screen"]

    batch = _scan_lines("souler[Bob]说：:play 晴天", from_backfill=True)
    assert [m.source for m in batch.commands] == ["backfill"]


def test_build_message_batch_marks_commands_as_intake_classified():
    """The marker is what tells the queue to leave the message alone."""
    batch = build_message_batch([classify_chat_line("souler[Bob]说：:play 晴天")])

    assert [m.intake_classified for m in batch.commands] == [True]
    # Queue-grammar output must NOT carry the marker, or timers lose their `;`.
    assert MessageInfo(content=":play a;b", nickname="Bob").intake_classified is False


def test_ambient_command_silence_survives_the_drain_for_a_screen_command(monkeypatch):
    """`MessageQueue.put_message` rewrites `silent` via `dataclasses.replace`.

    That copy must carry the intake marker too, or a force-silenced screen
    command would fall back to the queue grammar and get truncated at `;`.
    """
    from ushareiplay.core.command_silence import command_silence

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    with command_silence(True):
        _scan_lines("souler[Bob]说：:play a;b")

    manager, captured = _real_command_manager()
    _drain(manager)

    assert [m.content for m in captured] == [":play a;b"]
    assert [m.silent for m in captured] == [True]