import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.models.message_info import MessageInfo


class FakeMessageDispatch:
    def __init__(self):
        self.screen_messages = []
        self.command_outputs = []

    def bind_handler(self, _handler):
        return self

    def send_screen_message(self, message, silent=False):
        self.screen_messages.append((message, silent))

    def send_for_message_info(self, message_info, response, silent=False):
        self.command_outputs.append((message_info.nickname, response, silent))
        return True


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []
        self.infos = []

    def warning(self, message):
        self.warnings.append(message)

    def error(self, message):
        self.errors.append(message)

    def info(self, message):
        self.infos.append(message)


class FakeObserver:
    def __init__(self):
        self.events = []

    def emit(self, name, **kwargs):
        self.events.append((name, kwargs))


class FakeRuntime:
    def __init__(self, controller):
        self.controller = controller
        self.obs = controller.obs
        self.session_reasons = []

    def emit(self, event, **kwargs):
        self.obs.emit(event, **kwargs)

    @asynccontextmanager
    async def ui_session(self, reason):
        self.session_reasons.append(reason)
        yield


class FlakyCommand:
    def __init__(self, fail_times=1):
        self.attempts = 0
        self.fail_times = fail_times

    async def process(self, message_info, parameters):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            return {"error": f"Attempt {self.attempts} failed"}
        return {"song": "Test Song", "singer": "Test Singer", "album": "Test Album"}


def make_manager():
    controller = SimpleNamespace(
        obs=FakeObserver(),
        soul_handler=object(),
        music_handler=object(),
    )
    runtime = FakeRuntime(controller)
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager.configure_runtime(runtime)
    manager._logger = FakeLogger()
    manager._handler = SimpleNamespace(config={"system_users": ["Console"]})
    return manager, runtime, controller


def test_command_retry_success_on_second_attempt(monkeypatch):
    manager, runtime, controller = make_manager()
    flaky = FlakyCommand(fail_times=1)
    dispatch = FakeMessageDispatch()

    manager._message_dispatch = dispatch
    monkeypatch.setattr(manager, "get_command", lambda prefix: flaky)

    command_info = {
        "prefix": "play",
        "retry": True,
        "parameters": ["test"],
        "response_template": "{song} - {singer}",
        "error_template": "Failed: {error}",
    }
    msg = MessageInfo(content="play test", nickname="Console")

    response = asyncio.run(manager.process_command(flaky, msg, command_info))

    assert flaky.attempts == 2
    assert "Test Song - Test Singer" in response
    assert any("retrying (1/1)" in w for w in manager.logger.warnings)

    retry_events = [e for e in controller.obs.events if e[0] == "command.retry"]
    assert len(retry_events) == 1
    assert retry_events[0][1]["ctx"]["prefix"] == "play"


def test_command_retry_fails_on_both_attempts(monkeypatch):
    manager, runtime, controller = make_manager()
    flaky = FlakyCommand(fail_times=2)
    dispatch = FakeMessageDispatch()

    manager._message_dispatch = dispatch
    monkeypatch.setattr(manager, "get_command", lambda prefix: flaky)

    command_info = {
        "prefix": "play",
        "retry": True,
        "parameters": ["test"],
        "response_template": "{song} - {singer}",
        "error_template": "Failed: {error}",
    }
    msg = MessageInfo(content="play test", nickname="Console")

    response = asyncio.run(manager.process_command(flaky, msg, command_info))

    assert flaky.attempts == 2
    assert "Failed: Attempt 2 failed" in response
    assert any("retrying (1/1)" in w for w in manager.logger.warnings)


def test_command_no_retry_when_disabled(monkeypatch):
    manager, runtime, controller = make_manager()
    flaky = FlakyCommand(fail_times=1)
    dispatch = FakeMessageDispatch()

    manager._message_dispatch = dispatch
    monkeypatch.setattr(manager, "get_command", lambda prefix: flaky)

    command_info = {
        "prefix": "play",
        "retry": False,
        "parameters": ["test"],
        "response_template": "{song} - {singer}",
        "error_template": "Failed: {error}",
    }
    msg = MessageInfo(content="play test", nickname="Console")

    response = asyncio.run(manager.process_command(flaky, msg, command_info))

    assert flaky.attempts == 1
    assert "Failed: Attempt 1 failed" in response
    assert len(manager.logger.warnings) == 0
    retry_events = [e for e in controller.obs.events if e[0] == "command.retry"]
    assert len(retry_events) == 0
