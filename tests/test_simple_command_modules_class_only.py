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
    "mode",
    "next",
    "notice",
    "pack",
    "pause",
    "playlist",
    "say",
    "seat",
    "skip",
    "vol",
}


def test_simple_command_modules_are_class_only():
    commands_dir = Path(__file__).resolve().parents[1] / "src" / "ushareiplay" / "commands"

    for module_name in sorted(SIMPLE_COMMAND_MODULES):
        source = (commands_dir / f"{module_name}.py").read_text()

        assert "def create_command(" not in source, module_name
        assert "command = None" not in source, module_name
