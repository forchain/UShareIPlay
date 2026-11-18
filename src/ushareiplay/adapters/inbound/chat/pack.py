"""福袋命令：薄适配器，将子命令解析与调度委托给 LuckPackService。"""

import traceback

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.room.domain import PACK_USAGE


class PackCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = 'Failed to open luck pack'

    def __init__(self, controller):
        super().__init__(controller)
        self.luck_pack = controller.luck_pack

    async def do_process(self, message_info, parameters):
        """Process pack command to list/open luck packs or redeem heat points."""
        self.luck_pack.auto_mode = False
        subcommand = parameters[0].lower() if parameters else ''
        if subcommand == 'redeem':
            if len(parameters) > 1:
                return {'message': PACK_USAGE}
            return self.luck_pack.redeem_heat()
        if subcommand == 'list':
            if len(parameters) > 1:
                return {'message': PACK_USAGE}
            return self.luck_pack.list_packs()
        if subcommand == 'open':
            return self.luck_pack.open_pack(parameters[1:])
        if subcommand:
            return {'message': f'未知子命令，{PACK_USAGE}'}
        return self.luck_pack.list_packs()

    def update(self):
        """Check room count and auto open pack if needed."""
        try:
            self.luck_pack.update()
        except Exception:
            self.handler.log_error(f"Error in pack update: {traceback.format_exc()}")
