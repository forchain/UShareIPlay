from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.playback.domain import PlaybackMode, PlaybackRequest


class AlbumCommand(BaseCommand):
    """`:album [query]` —— 播某张专辑；不带参数时播当前这首所在专辑。"""

    handler_attr = "music_handler"

    async def do_process(self, message_info, parameters):
        result = await self.controller.play_song.execute(
            PlaybackRequest(
                mode=PlaybackMode.ALBUM,
                query=" ".join(parameters),
                requester=message_info.nickname,
            )
        )
        return result.as_response()
