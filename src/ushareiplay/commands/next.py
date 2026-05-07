import traceback
from ushareiplay.core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

class NextCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        query = ' '.join(parameters)
        self.soul_handler.ensure_mic_active()
        info = self.play_next(query)
        return info

    def play_next(self, query):
        info = self.music_handler.play_next(query)
        return info
