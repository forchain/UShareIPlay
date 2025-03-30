import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    ktv_command = KtvCommand(controller)
    controller.ktv_command = ktv_command
    return ktv_command

command = None

class KtvCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        # Toggle KTV mode
        enable = True
        if len(parameters) > 0:
            enable = parameters[0] == '1'

        # Toggle KTV mode
        result = self.music_handler.toggle_ktv_mode(enable)
        return result
