import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from ushareiplay.managers.command_manager import CommandManager


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def error(self, message):
        self.messages.append(("error", message))


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


class FakeCommand:
    async def process(self, message_info, parameters):
        return {"song": parameters[0]}


def make_manager(tmp_path):
    controller = SimpleNamespace(
        obs=FakeObserver(),
        soul_handler=object(),
        music_handler=object(),
        marker="ok",
    )
    runtime = FakeRuntime(controller)
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager.configure_runtime(runtime)
    manager._logger = FakeLogger()
    manager._handler = SimpleNamespace(config={"system_users": ["Console"]})
    manager.commands_path = tmp_path
    return manager, runtime, controller


def test_load_command_module_uses_injected_runtime_controller(tmp_path):
    command_file = tmp_path / "demo.py"
    command_file.write_text(
        "\n".join(
            [
                "from ushareiplay.core.base_command import BaseCommand",
                "",
                "class DemoCommand(BaseCommand):",
                "    def __init__(self, controller):",
                "        super().__init__(controller)",
                "        self.controller.loaded_by_command_manager = True",
                "",
                "    async def process(self, message_info, parameters):",
                "        return {'song': self.controller.marker}",
            ]
        ),
        encoding="utf-8",
    )
    manager, runtime, controller = make_manager(tmp_path)

    module = manager.load_command_module("demo")

    assert module is not None
    assert module.command is not None
    assert module.command.controller is runtime.controller
    assert controller.loaded_by_command_manager is True
    result = asyncio.run(module.command.process(None, []))
    assert result == {"song": "ok"}


def test_process_command_uses_runtime_for_observability_and_ui_session():
    manager, runtime, controller = make_manager(Path("."))
    message_info = SimpleNamespace(content=":demo abc", nickname="Console")
    command_info = {
        "parameters": ["abc"],
        "prefix": ":demo",
        "response_template": "ok {song}",
        "error_template": "error {error}",
    }

    result = asyncio.run(
        manager.process_command(FakeCommand(), message_info, command_info)
    )

    assert result == "ok abc @Console"
    assert runtime.session_reasons == ["command::demo"]
    assert [event[0] for event in controller.obs.events] == [
        "command.received",
        "command.dispatch",
        "command.result",
    ]
