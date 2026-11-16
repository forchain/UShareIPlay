from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback_muting import PlaybackMuting


class SkipCommand(BaseCommand):
    """跳过当前歌曲。

    守护先行：被拒绝的切歌不碰麦克风。守护通过后才在 PlaybackMuting 内执行
    `skip_song()`，静音只覆盖真正的切歌过程。
    """

    async def do_process(self, message_info, parameters):
        error = await self.playlist_adoption.guard_switch(message_info.nickname)
        if error:
            return error
        with PlaybackMuting.instance().guard():
            return MusicManager.instance().skip_song()
