from ushareiplay.core.command_catalogue import DEFAULT_COMMAND_ROOTS

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
    for filename in STATEFUL_COMMAND_MODULES:
        path = next(
            (root / filename for root in DEFAULT_COMMAND_ROOTS if (root / filename).is_file()),
            None,
        )
        assert path is not None, f"{filename} 在任何命令根目录中都不存在"
        source = path.read_text(encoding="utf-8")
        assert "def create_command(" not in source, filename
        assert "command = None" not in source, filename
