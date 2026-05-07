from __future__ import annotations

from ushareiplay.core.base_command import BaseCommand
class HelpCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        cfg = getattr(self.controller, "config", {}) or {}
        commands = (cfg.get("commands") or [])

        # 保持在 Soul 500 字限制内；CommandManager 还会追加 " @用户"。
        essential_order = [
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
        ]
        usage_hint = {
            "help": ":help 帮助",
            "play": ":play 歌名",
            "next": ":next 歌名",
            "skip": ":skip",
            "pause": ":pause 1/0",
            "vol": ":vol 0~15",
            "lyrics": ":lyrics",
            "fav": ":fav 收藏",
            "info": ":info",
            "singer": ":singer 歌手",
            "topic": ":topic 话题",
        }

        available = set()
        for c in commands:
            if not isinstance(c, dict):
                continue
            p = (c.get("prefix") or "").strip()
            if not p:
                continue
            available.add(p)

        lines = []
        lines.append("帮助")
        for prefix in essential_order:
            if prefix in available:
                lines.append(usage_hint[prefix])
        lines.append("更多: :playlist/:album/:radio/:timer/:admin")

        return {"help": "\n".join(lines).rstrip()}
