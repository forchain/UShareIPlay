import traceback
from ..core.base_command import BaseCommand
from ..managers.admin_manager import AdminManager

def create_command(controller):
    admin_command = AdminCommand(controller)
    controller.admin_command = admin_command
    return admin_command

command = None

class AdminCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.admin_manager = AdminManager(controller.soul_handler)

    async def process(self, message_info, parameters):
        # Get parameter
        if len(parameters) == 0:
            return {
                'error': 'Missing parameter. Use: :admin [1|0]',
                'user': message_info.nickname
            }

        try:
            enable = int(parameters[0]) == 1
            return await self.admin_manager.manage_admin(message_info, enable)
        except ValueError:
            return {
                'error': 'Invalid parameter. Use: :admin [1|0]',
                'user': message_info.nickname
            }
        except Exception as e:
            self.soul_handler.logger.error(f"Error in admin command: {traceback.format_exc()}")
            return {
                'error': str(e),
                'user': message_info.nickname
            }
