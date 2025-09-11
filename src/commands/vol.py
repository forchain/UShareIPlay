import traceback

from ..managers.music_manager import MusicManager
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    volume_command = VolumeCommand(controller)
    controller.volume_command = volume_command
    return volume_command

command = None

class VolumeCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        # Parse volume parameter
        delta = None
        if len(parameters) > 0:
            try:
                delta = int(parameters[0])
            except ValueError:
                return {
                    'error': 'Invalid parameter, must be a number',
                }

        # Adjust volume
        result = MusicManager.instance().adjust_volume(delta)
        return result
