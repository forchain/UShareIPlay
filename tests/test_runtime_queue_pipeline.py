import asyncio
import logging
from collections import deque


def _run(coro):
    return asyncio.run(coro)


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
        handler=handler, command_manager=command_manager, obs=obs, logger=handler.logger
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
        handler=handler, command_manager=command_manager, logger=handler.logger
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
        handler=handler, command_manager=command_manager, logger=handler.logger
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
        handler=handler, command_manager=command_manager, logger=handler.logger
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
        handler=handler, command_manager=command_manager, logger=handler.logger
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
        handler=handler, command_manager=command_manager, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == []
    assert [m.content for m in command_manager.received] == ["＄info"]


def test_process_new_messages_accepts_dollar_prefix_and_keeps_content():
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_new")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    original_cmd_instance = CommandManager.instance
    try:
        fake_command_manager = _FakeCommandManager()
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = object.__new__(MessageManager)
        manager._handler = _FakeSoulHandler()
        manager._chat_logger = logging.getLogger("test_chat_logger_new")
        manager.recent_chats = deque(maxlen=3)
        manager.latest_chats = deque(maxlen=3)
        manager.latest_chats.clear()
        manager.latest_chats.append("souler[Alice]说：$play 123")

        messages = _run(manager.process_new_messages())

        assert [m.content for m in messages] == ["$play 123"]
        assert [m.content for m in fake_command_manager.received] == ["$play 123"]
        assert [m.nickname for m in fake_command_manager.received] == ["Alice"]
    finally:
        CommandManager.instance = original_cmd_instance


def test_process_new_messages_accepts_fullwidth_dollar_prefix_and_keeps_content():
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_new_fullwidth")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    original_cmd_instance = CommandManager.instance
    try:
        fake_command_manager = _FakeCommandManager()
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = object.__new__(MessageManager)
        manager._handler = _FakeSoulHandler()
        manager._chat_logger = logging.getLogger("test_chat_logger_new_fullwidth")
        manager.recent_chats = deque(maxlen=3)
        manager.latest_chats = deque(maxlen=3)
        manager.latest_chats.clear()
        manager.latest_chats.append("souler[Alice]说：＄info")

        messages = _run(manager.process_new_messages())

        assert [m.content for m in messages] == ["＄info"]
        assert [m.content for m in fake_command_manager.received] == ["＄info"]
        assert [m.nickname for m in fake_command_manager.received] == ["Alice"]
    finally:
        CommandManager.instance = original_cmd_instance


def test_process_new_messages_skips_non_command_and_keeps_following_dollar_command():
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_new_mixed")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    original_cmd_instance = CommandManager.instance
    try:
        fake_command_manager = _FakeCommandManager()
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = object.__new__(MessageManager)
        manager._handler = _FakeSoulHandler()
        manager._chat_logger = logging.getLogger("test_chat_logger_new_mixed")
        manager.recent_chats = deque(maxlen=3)
        manager.latest_chats = deque(maxlen=3)
        manager.latest_chats.clear()
        manager.latest_chats.append("souler[Alice]说：hello")
        manager.latest_chats.append("souler[Alice]说：$play 123")

        messages = _run(manager.process_new_messages())

        assert [m.content for m in messages] == ["$play 123"]
        assert [m.content for m in fake_command_manager.received] == ["$play 123"]
    finally:
        CommandManager.instance = original_cmd_instance


def test_process_new_messages_accepts_ascii_colon_in_chat_prefix():
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_ascii_colon")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    original_cmd_instance = CommandManager.instance
    try:
        fake_command_manager = _FakeCommandManager()
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = object.__new__(MessageManager)
        manager._handler = _FakeSoulHandler()
        manager._chat_logger = logging.getLogger("test_chat_logger_ascii_colon")
        manager.recent_chats = deque(maxlen=3)
        manager.latest_chats = deque(maxlen=3)
        manager.latest_chats.clear()
        manager.latest_chats.append("souler[Alice]说:$info")

        messages = _run(manager.process_new_messages())

        assert [m.content for m in messages] == ["$info"]
        assert [m.content for m in fake_command_manager.received] == ["$info"]
    finally:
        CommandManager.instance = original_cmd_instance


def test_process_missed_messages_accepts_dollar_prefix_and_queues_command():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_missed")
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

    manager = object.__new__(MessageManager)
    manager._handler = _FakeSoulHandler()
    manager._chat_logger = logging.getLogger("test_chat_logger_missed")
    manager._recovery_manager = None
    manager.recent_chats = deque(maxlen=3)
    manager.latest_chats = deque(maxlen=3)
    manager.recent_chats.clear()
    manager.latest_chats.clear()
    manager.recent_chats.append("souler[Anchor]说：:noop")

    queue = MessageQueue.instance()
    _run(queue.clear_queue())

    command_set = _run(manager.process_missed_messages())

    queued_messages = list(_run(queue.get_all_messages()).values())

    assert command_set is not None
    assert "$play later" in command_set
    assert any(m.content == "$play later" and m.nickname == "Bob" for m in queued_messages)


def test_message_content_update_logic_does_not_drain_runtime_queue():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.info_manager import InfoManager
    from ushareiplay.models.message_info import MessageInfo

    class _FakeCmdMgr:
        def update_commands(self):
            return None

    class _FakeInfoMgr:
        def update_playback_info_cache(self):
            return None

    original_cmd_instance = CommandManager.instance
    original_info_instance = InfoManager.instance
    CommandManager.instance = classmethod(lambda cls: _FakeCmdMgr())
    InfoManager.instance = classmethod(lambda cls: _FakeInfoMgr())
    try:
        queue = MessageQueue.instance()
        _run(queue.clear_queue())
        _run(queue.put_message(MessageInfo(content=":timer list", nickname="Timer")))

        handler = _FakeHandler()
        event = MessageContentEvent(handler)
        _run(event._process_update_logic())

        assert queue.get_queue_size() == 1
    finally:
        CommandManager.instance = original_cmd_instance
        InfoManager.instance = original_info_instance


def test_message_content_event_dispatches_dollar_command(monkeypatch):
    from ushareiplay.events import message_content as message_content_module
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeMessageManager:
        def __init__(self):
            self.recent_chats = deque(maxlen=3)
            self.latest_chats = deque(maxlen=3)
            self.processed_new = False
            self.processed_missed = False

        def is_user_return_message(self, _content):
            return False, ""

        async def process_new_messages(self):
            self.processed_new = True

        async def process_missed_messages(self):
            self.processed_missed = True

    class _FakeChatLogger:
        def critical(self, _message):
            return None

        def info(self, _message):
            return None

    fake_manager = _FakeMessageManager()
    original_message_manager_instance = MessageManager.instance
    monkeypatch.setattr(MessageManager, "instance", classmethod(lambda cls: fake_manager))
    monkeypatch.setattr(
        message_content_module,
        "get_chat_logger",
        lambda _config=None: _FakeChatLogger(),
        raising=False,
    )
    try:
        event = MessageContentEvent(_FakeHandler())

        _run(event.handle("message_content", [_FakeWrapper("souler[Outlier]说：$info")]))

        assert fake_manager.processed_new is True
    finally:
        MessageManager.instance = original_message_manager_instance
