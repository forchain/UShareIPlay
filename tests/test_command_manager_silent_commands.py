import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from ushareiplay.managers.command_manager import CommandManager


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def error(self, message):
        self.messages.append(("error", message))


class _Runtime:
    def __init__(self):
        self.events = []
        self.session_reasons = []

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs))

    @asynccontextmanager
    async def ui_session(self, reason):
        self.session_reasons.append(reason)
        yield


class _Handler:
    def __init__(self):
        self.sent = []
        self.config = {"system_users": ["Console"]}
        self.logger = _Logger()

    def send_message(self, message):
        from ushareiplay.core.command_silence import is_command_silent

        if is_command_silent():
            return None
        self.sent.append(message)


class _Command:
    async def process(self, message_info, parameters):
        return {"message": f"processed {' '.join(parameters)}".strip()}


class _DirectSendCommand:
    def __init__(self, handler):
        self.handler = handler

    async def process(self, message_info, parameters):
        self.handler.send_message("inside command")
        return {"message": "done"}


class _QueueingCommand:
    async def process(self, message_info, parameters):
        from ushareiplay.core.message_queue import MessageQueue
        from ushareiplay.models.message_info import MessageInfo

        await MessageQueue.instance().put_message(
            MessageInfo(content="queued text;:demo queued", nickname=message_info.nickname)
        )
        return {"message": "queued"}


def _make_manager(commands=None):
    runtime = _Runtime()
    handler = _Handler()
    controller = SimpleNamespace(soul_handler=handler, music_handler=object())
    runtime.controller = controller

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager.configure_runtime(runtime)
    manager.controller = controller
    manager._handler = handler
    manager._logger = handler.logger
    manager.initialize_parser(
        commands
        or [
            {
                "prefix": "demo",
                "level": 1,
                "response_template": "{message}",
                "error_template": "{error}",
            }
        ]
    )
    return manager, runtime, handler


def test_slash_command_suppresses_screen_messages_but_still_executes(monkeypatch):
    manager, runtime, handler = _make_manager()
    command = _Command()
    monkeypatch.setattr(manager, "get_command", lambda _cmd: command)

    processed = asyncio.run(
        manager.handle_message_commands(
            [SimpleNamespace(content="/demo abc", nickname="Console")]
        )
    )

    assert processed == 1
    assert handler.sent == []
    assert [event[0] for event in runtime.events] == [
        "command.received",
        "command.dispatch",
        "command.result",
    ]


def test_fullwidth_slash_command_suppresses_screen_messages(monkeypatch):
    manager, _runtime, handler = _make_manager()
    command = _Command()
    monkeypatch.setattr(manager, "get_command", lambda _cmd: command)

    processed = asyncio.run(
        manager.handle_message_commands(
            [SimpleNamespace(content="／demo abc", nickname="Console")]
        )
    )

    assert processed == 1
    assert handler.sent == []


def test_colon_command_keeps_existing_screen_messages(monkeypatch):
    manager, _runtime, handler = _make_manager()
    command = _Command()
    monkeypatch.setattr(manager, "get_command", lambda _cmd: command)

    processed = asyncio.run(
        manager.handle_message_commands(
            [SimpleNamespace(content=":demo abc", nickname="Console")]
        )
    )

    assert processed == 1
    assert len(handler.sent) == 2
    assert handler.sent[0].endswith("demo ... @Console")
    assert handler.sent[1] == "processed abc @Console"


def test_silent_lifecycle_suppresses_direct_command_send_message():
    manager, _runtime, handler = _make_manager()
    message_info = SimpleNamespace(content="/demo", nickname="Console")
    command_info = {
        "parameters": [],
        "prefix": "demo",
        "silent": True,
        "level": 1,
        "response_template": "{message}",
        "error_template": "{error}",
    }

    response = asyncio.run(
        manager.process_command(_DirectSendCommand(handler), message_info, command_info)
    )

    assert response == "done @Console"
    assert handler.sent == []


def test_silent_lifecycle_marks_queued_keyword_commands_silent(monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer

    queue = MessageQueue.instance()
    asyncio.run(queue.clear_queue())

    manager, _runtime, handler = _make_manager()
    monkeypatch.setattr(manager, "get_command", lambda _cmd: _Command())
    message_info = SimpleNamespace(content="/keyword exec demo", nickname="Console")
    command_info = {
        "parameters": ["exec", "demo"],
        "prefix": "keyword",
        "silent": True,
        "level": 1,
        "response_template": "{message}",
        "error_template": "{error}",
    }

    response = asyncio.run(
        manager.process_command(_QueueingCommand(), message_info, command_info)
    )
    drained, command_count = asyncio.run(
        RuntimeQueueDrainer(
            handler=handler,
            command_manager=manager,
        ).drain()
    )

    assert response == "queued @Console"
    assert drained == 1
    assert command_count == 1
    assert handler.sent == []
