import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    skip_command = SkipCommand(controller)
    controller.skip_command = skip_command
    return skip_command

command = None

class SkipCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    def process(self, message_info, parameters):
        result = self.music_handler.skip_song()
        return result
