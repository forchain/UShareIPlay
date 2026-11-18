from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.playback.domain import PlaybackMode, PlaybackRequest


class PlaylistCommand(BaseCommand):
    """`:playlist <query>` 切到某个歌单；裸 `:playlist` 查询当前队列。"""

    handler_attr = "music_handler"

    async def do_process(self, message_info, parameters):
        if not parameters:
            return self.handler.get_playlist_info()

        result = await self.controller.play_song.execute(
            PlaybackRequest(
                mode=PlaybackMode.PLAYLIST,
                query=" ".join(parameters),
                requester=message_info.nickname,
            )
        )
        return result.as_response()
