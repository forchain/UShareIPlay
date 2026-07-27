import asyncio
from types import SimpleNamespace
import logging
from collections import deque


def _run(coro):
    return asyncio.run(coro)


def _with_ui_components(handler):
    handler.key_actions = handler
    handler.gesture_handler = handler
    handler.element_finder = handler
    return handler


class _FakeObs:
    def __init__(self):
        self.events = []

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs))


class _FakeHandler:
    def __init__(self):
        self.sent = []
        self.logger = logging.getLogger("test_runtime_queue")
        self.config = {"logging": {"directory": "logs"}}
        self.controller = None

    def send_message(self, message):
        self.sent.append(message)


class _FakeCommandManager:
    def __init__(self):
        self.received = []

    async def execute_command_messages(self, messages):
        self.received.extend(messages)
        return len(messages)

    async def execute_runtime_queue_messages(self, queue_messages, send_screen_message=None):
        from ushareiplay.managers.command_manager import CommandManager

        manager = CommandManager.__new__(CommandManager)
        manager.__init__()
        manager._logger = logging.getLogger("test_runtime_queue_fake_command_manager")
        manager.execute_command_messages = self.execute_command_messages
        return await manager.execute_runtime_queue_messages(
            queue_messages,
            send_screen_message=send_screen_message,
        )

    async def execute_chat_scan(self, rows):
        from ushareiplay.managers.command_manager import CommandManager

        manager = CommandManager.__new__(CommandManager)
        manager.__init__()
        manager.execute_command_messages = self.execute_command_messages
        return await manager.execute_chat_scan(rows)


class _FakeWrapper:
    def __init__(self, content):
        self.content = content


def test_runtime_queue_drainer_routes_commands_and_plain_messages():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content="hello {user_name};:timer list", nickname="Alice")))

    obs = _FakeObs()
    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, obs=obs, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == ["hello Alice"]
    assert [m.content for m in command_manager.received] == [":timer list"]
    assert [m.nickname for m in command_manager.received] == ["Alice"]
    assert [e[0] for e in obs.events] == ["queue.drain.start", "queue.drain.end"]


def test_runtime_queue_drainer_propagates_silent_commands_and_suppresses_plain_messages():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(
        queue.put_message(
            MessageInfo(content="hello {user_name};:timer list", nickname="Alice", silent=True)
        )
    )

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == []
    assert [m.content for m in command_manager.received] == [":timer list"]
    assert [m.silent for m in command_manager.received] == [True]


def test_runtime_queue_drainer_propagates_sleep_exempt_to_split_commands():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(
        queue.put_message(
            MessageInfo(
                content=":mode random;:playlist Sugar",
                nickname="Alice",
                sleep_exempt=True,
            )
        )
    )

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 2
    assert [m.content for m in command_manager.received] == [":mode random", ":playlist Sugar"]
    assert [m.sleep_exempt for m in command_manager.received] == [True, True]


def test_runtime_queue_drainer_treats_slash_parts_as_silent_commands():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content="hello;/timer list", nickname="Alice")))

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == ["hello"]
    assert [m.content for m in command_manager.received] == ["/timer list"]
    assert [m.silent for m in command_manager.received] == [True]


def test_runtime_queue_drainer_routes_dollar_parts_as_private_commands():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content="hello;$info", nickname="Alice")))

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == ["hello"]
    assert [m.content for m in command_manager.received] == ["$info"]
    assert [m.nickname for m in command_manager.received] == ["Alice"]


def test_runtime_queue_drainer_routes_fullwidth_dollar_parts_as_private_commands():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content="＄info", nickname="Alice")))

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == []
    assert [m.content for m in command_manager.received] == ["＄info"]


def _build_live_batch_manager(monkeypatch):
    """Build a CommandManager suitable for live-batch tests."""
    from ushareiplay.managers.command_manager import CommandManager

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager._handler = _with_ui_components(_FakeHandler())
    manager._chat_logger = logging.getLogger("test_chat_logger")
    manager._recent_chats = deque(maxlen=3)
    manager._latest_chats = deque(maxlen=3)

    received = []

    async def _capture(messages):
        received.extend(messages)
        return len(messages)

    async def _no_recover():
        return None

    monkeypatch.setattr(manager, "execute_command_messages", _capture)
    monkeypatch.setattr(manager, "recover_missed_history", _no_recover)
    return manager, received


def test_process_live_batch_accepts_dollar_prefix_and_keeps_content(monkeypatch):
    manager, received = _build_live_batch_manager(monkeypatch)

    result = _run(manager.process_live_batch(["souler[Alice]说：$play 123"]))

    assert [m.content for m in received] == ["$play 123"]
    assert [m.nickname for m in received] == ["Alice"]
    assert result["missed"] is False
    assert result["command_count"] == 1
    # Anchor advanced to the freshly-classified tail.
    assert list(manager._recent_chats) == ["souler[Alice]说：$play 123"]


def test_process_live_batch_accepts_fullwidth_dollar_prefix_and_keeps_content(monkeypatch):
    manager, received = _build_live_batch_manager(monkeypatch)

    _run(manager.process_live_batch(["souler[Alice]说：＄info"]))

    assert [m.content for m in received] == ["＄info"]
    assert [m.nickname for m in received] == ["Alice"]


def test_process_live_batch_skips_non_command_and_keeps_following_dollar_command(monkeypatch):
    manager, received = _build_live_batch_manager(monkeypatch)

    _run(
        manager.process_live_batch(
            ["souler[Alice]说：hello", "souler[Alice]说：$play 123"]
        )
    )

    assert [m.content for m in received] == ["$play 123"]


def test_process_live_batch_accepts_ascii_colon_in_chat_prefix(monkeypatch):
    manager, received = _build_live_batch_manager(monkeypatch)

    _run(manager.process_live_batch(["souler[Alice]说:$info"]))

    assert [m.content for m in received] == ["$info"]


def test_recover_missed_history_accepts_dollar_prefix_and_queues_command(monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_recover_missed_history")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

        def scroll_container_until_element(self, *_args, **_kwargs):
            return (
                "message_content",
                object(),
                ["souler[Bob]说：$play later", "souler[Bob]说：:timer list"],
            )

        def send_message(self, _message):
            return None

    fake_command_manager = _FakeCommandManager()
    monkeypatch.setattr(CommandManager, "instance", classmethod(lambda cls: fake_command_manager), raising=False)
    monkeypatch.setattr(MessageManager, "_get_seat_manager", lambda self: None, raising=False)
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager._handler = _with_ui_components(_FakeSoulHandler())
    manager._chat_logger = logging.getLogger("test_chat_logger_missed")
    manager._recent_chats = deque(maxlen=3)
    manager._latest_chats = deque(maxlen=3)
    manager._recent_chats.append("souler[Anchor]说：:noop")

    queue = MessageQueue.instance()
    _run(queue.clear_queue())

    command_set = _run(manager.recover_missed_history())

    queued_messages = list(_run(queue.get_all_messages()).values())

    assert command_set is not None
    assert "$play later" in command_set
    assert any(m.content == "$play later" and m.nickname == "Bob" for m in queued_messages)


def test_recover_missed_history_sends_empty_message_after_finding_anchor(monkeypatch):
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_recover_missed_anchor")
            self.config = {"logging": {"directory": "logs"}}
            self.sent_messages = []

        def switch_to_app(self):
            return True

        def scroll_container_until_element(self, *_args, **_kwargs):
            return "message_content", object(), ["兴趣主题已更换为「Turn Around」"]

        def send_message(self, message):
            self.sent_messages.append(message)

    handler = _with_ui_components(_FakeSoulHandler())
    monkeypatch.setattr(CommandManager, "instance", classmethod(lambda cls: object.__new__(CommandManager)), raising=False)
    monkeypatch.setattr(MessageManager, "_get_seat_manager", lambda self: None, raising=False)
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager._handler = handler
    manager._chat_logger = logging.getLogger("test_chat_logger_missed_anchor")
    manager._recent_chats = deque(["兴趣主题已更换为「Turn Around」"], maxlen=3)
    manager._latest_chats = deque(maxlen=3)

    assert _run(manager.recover_missed_history()) == set()
    # send_message("") should be called to scroll back to bottom
    assert handler.sent_messages == [""]


def test_missed_detection_fallback_prevents_false_missed():
    """When content_list has more items than recent_chats.maxlen,
    the forward-matching fails but the anchor IS on screen.
    The fallback check should set missed=False."""
    from ushareiplay.managers.message_manager import MessageManager

    manager = object.__new__(MessageManager)
    manager._handler = None
    manager._chat_logger = logging.getLogger("test_fallback")
    manager._recovery_manager = None
    # recent_chats only holds 3, but screen shows 5 messages
    manager.recent_chats = deque(["msg_C", "msg_D", "msg_E"], maxlen=3)
    manager.latest_chats = deque(maxlen=3)

    # Simulate the matching logic from MessageContentEvent.handle()
    content_list = ["msg_A", "msg_B", "msg_C", "msg_D", "msg_E"]
    recent_len = len(manager.recent_chats)
    content_len = len(content_list)
    missed = False

    # Run the matching algorithm (copy from message_content.py)
    for i in range(recent_len):
        no_new = False
        for j in range(content_len):
            content = content_list[j]
            ii = i + j
            if ii < recent_len:
                recent_chat = manager.recent_chats[ii]
                if content != recent_chat:
                    break
                if ii == recent_len - 1 and j == content_len - 1:
                    no_new = True
                    break
            else:
                manager.latest_chats.append(content)
        if no_new:
            break
        if len(manager.latest_chats) > 0:
            break
        elif i == recent_len - 1:
            missed = True
            for c in content_list:
                manager.latest_chats.append(c)

    # Without the fallback, missed would be True
    assert missed is True

    # Now apply the fallback check (same as in message_content.py)
    if missed and recent_len > 0:
        last_recent = manager.recent_chats[-1]
        for idx, content in enumerate(content_list):
            if content == last_recent:
                missed = False
                manager.latest_chats.clear()
                for new_content in content_list[idx + 1:]:
                    manager.latest_chats.append(new_content)
                break

    # After fallback, missed should be False
    assert missed is False
    # No new messages after anchor
    assert len(manager.latest_chats) == 0


def test_process_live_batch_idle_outcome_does_not_drain_runtime_queue(monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
    from ushareiplay.models.message_info import MessageInfo

    class _FakeCommandManager:
        def update_commands(self):
            return None

    class _FakePlaybackBroadcaster:
        def update_playback_info_cache(self):
            return None

    fake_command_manager = _FakeCommandManager()
    fake_broadcaster = _FakePlaybackBroadcaster()
    monkeypatch.setattr(CommandManager, "instance", classmethod(lambda cls: fake_command_manager), raising=False)
    monkeypatch.setattr(
        PlaybackBroadcaster,
        "instance",
        classmethod(lambda cls: fake_broadcaster),
        raising=False,
    )

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content=":timer list", nickname="Timer")))

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager._handler = _with_ui_components(_FakeHandler())
    manager._chat_logger = logging.getLogger("test_idle_outcome")
    manager._recent_chats = deque(maxlen=3)
    manager._latest_chats = deque(maxlen=3)

    _run(manager.process_live_batch(["souler[Alice]说：hello world"]))

    assert queue.get_queue_size() == 1


def test_message_content_event_submits_rows_to_command_execution(monkeypatch):
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers.command_manager import CommandManager

    received = []

    class _FakeCommandManager:
        async def process_live_batch(self, rows):
            received.append(list(rows))

    fake_command_manager = _FakeCommandManager()
    monkeypatch.setattr(CommandManager, "instance", classmethod(lambda cls: fake_command_manager), raising=False)

    event = MessageContentEvent(_FakeHandler())
    _run(event.handle("message_content", [_FakeWrapper("souler[Outlier]说：$info")]))

    assert received == [["souler[Outlier]说：$info"]]
