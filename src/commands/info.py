import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    info_command = InfoCommand(controller)
    controller.info_command = info_command
    return info_command

command = None

class InfoCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    def process(self, message_info, parameters):
        result = self.music_handler.get_playback_info()
        result['player'] = self.controller.player_name
        return result
