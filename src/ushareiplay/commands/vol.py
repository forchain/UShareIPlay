from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.core.base_command import BaseCommand


class VolumeCommand(BaseCommand):
    async def do_process(self, message_info, parameters):
        # Parse volume parameter
        target_volume = None
        if len(parameters) > 0:
            target_volume, err = self.coerce_int(parameters[0], error='Invalid parameter, must be a number')
            if err:
                return {'error': err}
            # Validate volume range
            if target_volume < 0 or target_volume > 15:
                return {
                    'error': 'Volume must be between 0 and 15',
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
