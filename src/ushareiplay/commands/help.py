from __future__ import annotations

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.core.command_catalogue import CommandCatalogue


class HelpCommand(BaseCommand):
    async def do_process(self, message_info, parameters):
        catalogue = getattr(
            getattr(self.controller, "command_manager", None), "catalogue", None
        )
        if catalogue is None:
            catalogue = CommandCatalogue.from_config(
                getattr(self.controller, "config", {}) or {}
            )
        # 保持在 Soul 500 字限制内；CommandManager 还会追加 " @用户"。
        return {"help": "\n".join(catalogue.get_help_lines()).rstrip()}
