import traceback
from ushareiplay.core.base_command import BaseCommand


class EndCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = 'Failed to end party'

    def __init__(self, controller):
        super().__init__(controller)
        self.handler.logger.info("EndCommand initialized")
        self.party_service = controller.party_service
        self.party_service.initialize_party()

    async def do_process(self, message_info, parameters):
        """Process end command to close party"""
        return self.party_service.end_party()

    def update(self):
        """委托给 PartyService 处理派对管理逻辑"""
        try:
            self.party_service.update()
        except Exception:
            self.handler.log_error(f"Error in party management update: {traceback.format_exc()}")
