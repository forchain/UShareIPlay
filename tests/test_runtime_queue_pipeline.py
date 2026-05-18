import asyncio
import logging


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

    async def handle_message_commands(self, messages):
        self.received.extend(messages)


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
