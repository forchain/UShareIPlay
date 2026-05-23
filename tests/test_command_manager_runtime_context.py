import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.models.message_info import MessageInfo


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


def test_extract_private_reply_and_normalize_dollar_prefix():
    manager, _runtime, _controller = make_manager(Path("."))

    private_reply, normalized = manager._extract_private_reply_and_normalize("$play abc")

    assert private_reply is True
    assert normalized == "play abc"


def test_extract_private_reply_and_normalize_fullwidth_dollar_prefix():
    manager, _runtime, _controller = make_manager(Path("."))

    private_reply, normalized = manager._extract_private_reply_and_normalize("＄info")

    assert private_reply is True
    assert normalized == "info"


def test_extract_private_reply_and_normalize_colon_prefix_unchanged():
    manager, _runtime, _controller = make_manager(Path("."))

    private_reply, normalized = manager._extract_private_reply_and_normalize(":help")

    assert private_reply is False
    assert normalized == "help"


def test_handle_message_commands_merges_existing_private_reply(monkeypatch):
    manager, _runtime, _controller = make_manager(Path("."))
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

    captured = {}

    async def _fake_process(command, message_info, command_info):
        captured["content"] = message_info.content
        captured["private_reply"] = message_info.private_reply
        return None

    monkeypatch.setattr(manager, "get_command", lambda _cmd: object())
    monkeypatch.setattr(manager, "process_command", _fake_process)
    monkeypatch.setattr(manager, "_send_screen_message", lambda *args, **kwargs: None)

    processed = asyncio.run(
        manager.handle_message_commands(
            [MessageInfo(content="$play abc", nickname="Console", private_reply=False)]
        )
    )

    assert processed == 1
    assert captured["content"] == "$play abc"
    assert captured["private_reply"] is True


def test_handle_message_commands_private_reply_keeps_confirmation_public(monkeypatch):
    manager, _runtime, _controller = make_manager(Path("."))
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

    sent_public = []
    sent_private = []

    async def _fake_process(_command, _message_info, _command_info):
        return "ok result @Console"

    monkeypatch.setattr(manager, "get_command", lambda _cmd: object())
    monkeypatch.setattr(manager, "process_command", _fake_process)

    def _fake_send_screen(message, silent=False):
        sent_public.append((message, silent))

    def _fake_send_private(message_info, response, silent=False):
        sent_private.append((message_info.nickname, response, silent))
        return True

    monkeypatch.setattr(manager, "_send_screen_message", _fake_send_screen)
    monkeypatch.setattr(manager, "_send_command_output", _fake_send_private)

    processed = asyncio.run(
        manager.handle_message_commands(
            [MessageInfo(content="$play abc", nickname="Console", private_reply=False)]
        )
    )

    assert processed == 1
    assert len(sent_public) == 1
    assert sent_public[0][0].endswith("play ... @Console")
    assert sent_public[0][1] is False
    assert sent_private == [("Console", "ok result @Console", False)]


def test_handle_message_commands_private_reply_error_routes_private(monkeypatch):
    manager, _runtime, _controller = make_manager(Path("."))
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

    sent_public = []
    sent_private = []

    async def _fake_process(_command, _message_info, _command_info):
        return "error boom @Console"

    monkeypatch.setattr(manager, "get_command", lambda _cmd: object())
    monkeypatch.setattr(manager, "process_command", _fake_process)

    def _fake_send_screen(message, silent=False):
        sent_public.append((message, silent))

    def _fake_send_private(message_info, response, silent=False):
        sent_private.append((message_info.nickname, response, silent))
        return True

    monkeypatch.setattr(manager, "_send_screen_message", _fake_send_screen)
    monkeypatch.setattr(manager, "_send_command_output", _fake_send_private)

    processed = asyncio.run(
        manager.handle_message_commands(
            [MessageInfo(content="$play abc", nickname="Console", private_reply=False)]
        )
    )

    assert processed == 1
    assert len(sent_public) == 1
    assert sent_public[0][0].endswith("play ... @Console")
    assert sent_public[0][1] is False
    assert sent_private == [("Console", "error boom @Console", False)]
