import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    mode_command = ModeCommand(controller)
    controller.mode_command = mode_command
    return mode_command

command = None

class ModeCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        if len(parameters) == 0:
            return {
            'error': 'Missing mode parameter'
        }
        try:
            mode = int(parameters[0])
            if mode not in [0, 1, -1]:
                raise ValueError

            # Change play mode
            result = self.music_handler.change_play_mode(mode)
            return result
        except ValueError:
            return {
                'error': 'Invalid mode parameter, must be 0, 1 or -1'
            }