import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    play_command = PlayCommand(controller)
    controller.play_command = play_command
    return play_command

command = None

class PlayCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    def process(self, message_info, parameters):
        query = ' '.join(parameters)
        self.soul_handler.ensure_mic_active()
        playing_info = self.music_handler.play_music(query)
        return playing_info
