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
    rendered = cfg["commands"]
    help_text = result["help"]

    prefixes_cfg = {c["prefix"] for c in (cfg.get("commands") or []) if isinstance(c, dict) and c.get("prefix")}
    prefixes_help = {p[1:] for p in _extract_prefixes_from_help(help_text)}

    missing = sorted(prefixes_cfg - prefixes_help)
    extra = sorted(prefixes_help - prefixes_cfg)

    assert not missing, f"help 缺少命令: {missing}"
    assert not extra, f"help 出现未知命令: {extra}"

    print("OK: help 输出与 config.yaml commands 同步")


if __name__ == "__main__":
    main()

