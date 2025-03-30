import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    admin_command = AdminCommand(controller)
    controller.admin_command = admin_command
    return admin_command

command = None

class AdminCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        # Get parameter
        if len(parameters) == 0:
            return {
                'user': message_info.nickname,
                'error': 'Missing parameter (1 for enable, 0 for disable)'
            }

        enable = parameters[0] == '1'
        # Manage admin status
        result = self.soul_handler.manage_admin(message_info, enable)
        return result
