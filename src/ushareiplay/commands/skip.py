from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.music_manager import MusicManager


class SkipCommand(BaseCommand):
    async def do_process(self, message_info, parameters):
        return MusicManager.instance().skip_song()
