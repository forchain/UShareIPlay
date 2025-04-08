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

    def pause_song(self, pause_state=None):
        """
        Pause/resume playback
        Args:
            pause_state: None for toggle, 1 for pause, 0 for play
        Returns:
            dict: Current playing info or error
        """
        try:
            # Get current playback info
            current_info = self.music_handler.get_playback_info()
            if 'error' in current_info:
                return current_info

            # Get current state
            is_playing = current_info['state'] == "Playing"

            # Determine if we need to change state
            should_pause = False
            if pause_state is None:
                # Toggle mode
                should_pause = is_playing
            else:
                # Explicit mode
                should_pause = pause_state == 1
                if (should_pause and not is_playing) or (not should_pause and is_playing):
                    # State already matches desired state
                    return {
                        'song': current_info['song'],
                        'singer': current_info['singer'],
                        'action': 'Paused' if not is_playing else 'Resumed'
                    }

            if should_pause:
                # If pausing, turn off mic first
                mic_result = self.controller.mic_command.toggle_mic(False)  # Turn mic off
                if 'error' in mic_result:
                    self.logger.warning(f"Failed to turn off mic: {mic_result['error']}")

            # Execute media control command
            self.music_handler.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'input keyevent KEYCODE_MEDIA_PLAY_PAUSE'
                }
            )
            self.music_handler.logger.info("Sent media play/pause key event")

            if not should_pause:
                # If resuming, turn on mic after resuming playback
                mic_result = self.controller.mic_command.toggle_mic(True)  # Turn mic on
                if 'error' in mic_result:
                    self.music_handler.logger.warning(f"Failed to turn on mic: {mic_result['error']}")

            return {
                'song': current_info['song'],
                'singer': current_info['singer'],
                'action': 'Paused' if should_pause else 'Resumed'
            }

        except Exception as e:
            self.music_handler.logger.error(f"Error controlling playback: {traceback.format_exc()}")
            return {'error': f'Failed to pause/resume song, {pause_state}'}

    async def process(self, message_info, parameters):
        pause_state = None
        if len(parameters) > 0:
            pause_state = int(parameters[0])
            if pause_state not in [0, 1]:
                return {
                    'error': 'Invalid parameter, must be 0 or 1',
                }

        return self.pause_song(pause_state)
