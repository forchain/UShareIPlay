import asyncio
from pathlib import Path
from types import SimpleNamespace

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.command_manager import CommandManager


class DummyController:
    def __init__(self):
        self.soul_handler = object()
        self.music_handler = object()
        self.marker = "ok"


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def error(self, message):
        self.messages.append(("error", message))


def test_load_command_module_instantiates_class_without_factory(tmp_path):
    (tmp_path / "demo.py").write_text(
        "\n".join(
            [
                "from ushareiplay.core.base_command import BaseCommand",
                "",
                "class DemoCommand(BaseCommand):",
                "    async def do_process(self, message_info, parameters):",
                "        return {'message': self.controller.marker}",
            ]
        ),
        encoding="utf-8",
    )

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager.commands_path = Path(tmp_path)
    manager.controller = DummyController()
    manager._logger = FakeLogger()
    manager._handler = SimpleNamespace(config={"system_users": []})

    module = manager.load_command_module("demo")

    assert module is not None
    assert hasattr(module, "command")
    assert isinstance(module.command, BaseCommand)
    assert module.command.controller is manager.controller
    result = asyncio.run(module.command.process(None, []))
    assert result == {"message": "ok"}
