from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.music_manager import MusicManager


class SkipCommand(BaseCommand):
    """跳过当前歌曲。

    守护与闭麦都由 `MusicManager.skip()` 负责：被守护拒绝时不碰麦克风，
    守护通过后才在 PlaybackMuting 内执行 `skip_song()`。
    """

    async def do_process(self, message_info, parameters):
        return await MusicManager.instance().skip(message_info.nickname)
