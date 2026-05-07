import traceback
from ushareiplay.core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

class SkipCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        result = self.music_handler.skip_song()
        return result
