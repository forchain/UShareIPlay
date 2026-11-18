from ushareiplay.adapters.inbound.chat.base_command import BaseCommand


class SkipCommand(BaseCommand):
    """跳过当前歌曲，交给 `SkipSong` 用例。"""

    async def do_process(self, message_info, parameters):
        return await self.controller.skip_song.execute(message_info.nickname)
