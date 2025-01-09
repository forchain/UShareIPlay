import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    accompaniment_command = AccompanimentCommand(controller)
    controller.accompaniment_command = accompaniment_command
    return accompaniment_command

command = None

class AccompanimentCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    def process(self, message_info, parameters):
        # Get parameter
        if len(parameters) == 0:
            return {
                'error': 'Missing parameter (on:1, off:0) for accompaniment command'
            }

        enable = parameters[0] == '1'
        # Toggle accompaniment mode
        result = self.music_handler.toggle_accompaniment(enable)
        return result
