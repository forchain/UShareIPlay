from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.music_manager import MusicManager


class SkipCommand(BaseCommand):
    playback_muting = True

    async def do_process(self, message_info, parameters):
        error = await self.playlist_adoption.guard_switch(message_info.nickname)
        if error:
            return error
        return MusicManager.instance().skip_song()
