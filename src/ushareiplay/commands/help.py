from __future__ import annotations

from ushareiplay.core.base_command import BaseCommand

def create_command(controller):
    help_command = HelpCommand(controller)
    controller.help_command = help_command
    return help_command

command = None

class HelpCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        cfg = getattr(self.controller, "config", {}) or {}
        commands = (cfg.get("commands") or [])

        def level_of(c: dict) -> int:
            try:
                return int(c.get("level", 0))
            except Exception:
                return 0

        # 常用命令的最小用法提示（避免“只有列表没用法”的体验）
        usage_hint = {
            "help": ":help",
            "play": ":play 歌名 歌手",
            "next": ":next 歌名 歌手",
            "skip": ":skip",
            "pause": ":pause 1/0",
            "fav": ":fav [0 语言]",
            "vol": ":vol [0~15]",
            "lyrics": ":lyrics",
            "info": ":info",
            "playlist": ":playlist 歌单",
            "singer": ":singer 歌手",
            "album": ":album 专辑",
            "mic": ":mic 0/1",
            "mode": ":mode 0/1/-1",
            "topic": ":topic 话题",
            "theme": ":theme 主题",
            "title": ":title 标题",
            "timer": ":timer add id 时间 命令",
            "radio": ":radio guess/daily/collection/sleep",
        }

        # 去重 + 稳定排序
        uniq: Dict[str, dict] = {}
        for c in commands:
            if not isinstance(c, dict):
                continue
            p = (c.get("prefix") or "").strip()
            if not p:
                continue
            uniq.setdefault(p, c)

        items = sorted(uniq.items(), key=lambda kv: (level_of(kv[1]), kv[0]))
        common = [(p, c) for (p, c) in items if level_of(c) <= 1]
        advanced = [(p, c) for (p, c) in items if level_of(c) > 1]

        lines = []
        lines.append("帮助（自动生成，以 config.yaml 的 commands 为准）")
        lines.append("")

        def emit_section(title: str, pairs: list[tuple[str, dict]]):
            if not pairs:
                return
            lines.append(title)
            for p, c in pairs:
                hint = usage_hint.get(p, f":{p}")
                lvl = level_of(c)
                lines.append(f"- {hint}  (level={lvl})")
            lines.append("")

        emit_section("常用", common)
        emit_section("高级", advanced)

        return {"help": "\n".join(lines).rstrip()}
