import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    pause_command = PauseCommand(controller)
    controller.pause_command = pause_command
    return pause_command

command = None

class PauseCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    def process(self, message_info, parameters):
        pause_state = None
        if len(parameters) > 0:
            pause_state = int(parameters[0])
            if pause_state not in [0, 1]:
                return {
                    'error': 'Invalid parameter, must be 0 or 1',
                }

        info = self.music_handler.pause_song(pause_state)
        return info
