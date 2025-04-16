import traceback
from ..core.base_command import BaseCommand
from ..managers.sleep_manager import SleepManager

def create_command(controller):
    sleep_command = SleepCommand(controller)
    controller.sleep_command = sleep_command
    return sleep_command


command = None


class SleepCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.sleep_manager = SleepManager(controller.soul_handler)

    async def process(self, message_info, parameters):
        """Process sleep command
        Args:
            message_info: MessageInfo object containing message details
            parameters: list of command parameters
        Returns:
            dict: Result with status info
        """
        try:
            if not parameters:
                return self.sleep_manager.get_sleep_mode()

            if len(parameters) != 1:
                return {'error': 'Invalid parameters. Usage: :sleep [on|off]'}

            param = parameters[0].lower()
            if param not in ['on', 'off']:
                return {'error': 'Invalid parameter. Use "on" or "off"'}

            return await self.sleep_manager.set_sleep_mode(message_info.username, param == 'on')
        except Exception as e:
            self.handler.log_error(f"Error processing sleep command: {traceback.format_exc()}")
            return {'error': f'Failed to process sleep command: {str(e)}'} 