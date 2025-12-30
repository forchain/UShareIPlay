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
        target_volume = None
        if len(parameters) > 0:
            try:
                target_volume = int(parameters[0])
                # Validate volume range
                if target_volume < 0 or target_volume > 15:
                    return {
                        'error': 'Volume must be between 0 and 15',
                    }
            except ValueError:
                return {
                    'error': 'Invalid parameter, must be a number',
                }

        # Adjust volume or get current volume
        result = MusicManager.instance().adjust_volume(target_volume)
        
        # Format the response message based on the result
        if 'error' in result:
            return result
        
        if result.get('current', False):
            # Getting current volume
            message = f"Current volume: {result['volume']}"
        else:
            # Adjusting volume
            message = f"Adjusted volume to {result['volume']}"
        
        return {'message': message}
