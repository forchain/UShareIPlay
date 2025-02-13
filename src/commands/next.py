import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    next_command = NextCommand(controller)
    controller.next_command = next_command
    return next_command

command = None

class NextCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    def process(self, message_info, parameters):
        query = ' '.join(parameters)
        self.soul_handler.ensure_mic_active()
        info = self.play_next(query)
        return info

    def play_next(self, query):
        info = self.music_handler.play_next(query)
        return info
