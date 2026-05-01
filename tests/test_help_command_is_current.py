import re

from ushareiplay.commands.help import HelpCommand
from ushareiplay.core.config_loader import ConfigLoader


class DummyController:
    def __init__(self, config):
        self.config = config
        # HelpCommand 不依赖 handler，但 BaseCommand 构造器要求这些属性存在
        self.soul_handler = None
        self.music_handler = None


def _extract_prefixes_from_help(text: str) -> set[str]:
    # accepts ':play' or full ':play xxx' lines
    return set(re.findall(r"(?m)^(?:-\s*)?(:[a-zA-Z0-9_]+)", text))


def main():
    cfg = ConfigLoader.load_config()
    ctl = DummyController(cfg)
    cmd = HelpCommand(ctl)

    # HelpCommand returns {"help": "..."}
    import asyncio

    result = asyncio.run(cmd.process(message_info=None, parameters=[]))
    assert isinstance(result, dict) and "help" in result
    help_text = result["help"]

    # Soul 消息上限是 500 字符，CommandManager 会追加执行人信息；正文保留约 10 字符余量。
    assert len(help_text) <= 490, f"help 输出过长: {len(help_text)} chars"

    essential_prefixes = {
        "help",
        "play",
        "next",
        "skip",
        "pause",
        "vol",
        "lyrics",
        "fav",
        "info",
        "singer",
        "topic",
    }
    prefixes_help = {p[1:] for p in _extract_prefixes_from_help(help_text)}

    missing = sorted(essential_prefixes - prefixes_help)

    assert not missing, f"help 缺少核心命令: {missing}"
    assert "recovery" not in prefixes_help, "help 不应展示不可执行的 recovery 命令"

    print("OK: help 输出精简且包含核心命令")


if __name__ == "__main__":
    main()
