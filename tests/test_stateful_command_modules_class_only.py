from pathlib import Path


STATEFUL_COMMAND_MODULES = [
    "album.py",
    "end.py",
    "fav.py",
    "lyrics.py",
    "mic.py",
    "play.py",
    "radio.py",
    "return.py",
    "room.py",
    "singer.py",
    "theme.py",
    "timer.py",
    "title.py",
    "topic.py",
]


def test_stateful_command_modules_are_class_only():
    commands_dir = Path(__file__).resolve().parents[1] / "src" / "ushareiplay" / "commands"

    for filename in STATEFUL_COMMAND_MODULES:
        source = (commands_dir / filename).read_text(encoding="utf-8")
        assert "def create_command(" not in source, filename
        assert "command = None" not in source, filename
