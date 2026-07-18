import traceback
from ushareiplay.core.base_command import BaseCommand


class EndCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = 'Failed to end party'

    def __init__(self, controller):
        super().__init__(controller)
        self.handler.logger.info("EndCommand initialized")

        # 初始化派对管理器
        from ushareiplay.managers.party_manager import PartyManager
        self.party_manager = PartyManager.instance()
        self.party_manager.initialize_party()

    async def do_process(self, message_info, parameters):
        """Process end command to close party"""
        # 委托给PartyManager处理
        return self.party_manager.end_party()

    def update(self):
        """委托给PartyManager处理派对管理逻辑"""
        try:
            # 将派对管理逻辑委托给PartyManager
            self.party_manager.update()
        except Exception as e:
            self.handler.log_error(f"Error in party management update: {traceback.format_exc()}")
