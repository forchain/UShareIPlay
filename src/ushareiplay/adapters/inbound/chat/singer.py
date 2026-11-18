from ushareiplay.adapters.inbound.chat.base_command import BaseCommand
from ushareiplay.modules.playback.domain import PlaybackMode, PlaybackRequest


class SingerCommand(BaseCommand):
    """`:singer <query>` —— 播某个歌手的歌。"""

    handler_attr = "music_handler"

    async def do_process(self, message_info, parameters):
        result = await self.controller.play_song.execute(
            PlaybackRequest(
                mode=PlaybackMode.SINGER,
                query=" ".join(parameters),
                requester=message_info.nickname,
            )
        )
        return result.as_response()
