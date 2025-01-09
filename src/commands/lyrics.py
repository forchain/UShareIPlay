import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    lyrics_command = LyricsCommand(controller)
    controller.lyrics_command = lyrics_command
    return lyrics_command

command = None

class LyricsCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    def process(self, message_info, parameters):
        # Get lyrics of current song
        # Parse parameters
        force_groups = 0
        params = parameters

        if params:
            try:
                # Try to parse first parameter as group number
                force_groups = int(params[0])
                # Remove group number from query
                query = ' '.join(params[1:])
            except ValueError:
                # First parameter is not a number, use entire query
                query = ' '.join(params)
        else:
            query = ""

        result = self.music_handler.query_lyrics(query, force_groups)
        if 'error' in result:
            return result

        groups = result['groups']
        l = 0
        for lyr in groups:
            l += len(lyr)
            self.soul_handler.send_message(lyr)

        prompt = f' {len(groups)} piece(s) of lyrics sent, {l} characters'
        # Send lyrics back to Soul using command's template
        return {
            'lyrics': prompt
        }
