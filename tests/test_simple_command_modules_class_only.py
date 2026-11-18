from pathlib import Path


SIMPLE_COMMAND_MODULES = {
    "acc",
    "admin",
    "alias",
    "enter",
    "exit",
    "gift",
    "help",
    "info",
    "keyword",
    "level",
    "mode",
    "next",
    "notice",
    "pack",
    "pause",
    "playlist",
    "recommend",
    "say",
    "seat",
    "skip",
    "vol",
}


def test_simple_command_modules_are_class_only():
    package_root = Path(__file__).resolve().parents[1] / "src" / "ushareiplay"
    commands_dirs = [
        package_root / "adapters" / "inbound" / "chat",
    ]

    for module_name in sorted(SIMPLE_COMMAND_MODULES):
        path = next(
            directory / f"{module_name}.py"
            for directory in commands_dirs
            if (directory / f"{module_name}.py").is_file()
        )
        source = path.read_text()

        assert "def create_command(" not in source, module_name
        assert "command = None" not in source, module_name
