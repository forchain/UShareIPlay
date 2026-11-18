from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.playback.domain import PlaybackRequest


class PlayCommand(BaseCommand):
    """`:play` —— 点歌、播放全部收藏、打开雷达电台。"""

    handler_attr = "music_handler"

    async def do_process(self, message_info, parameters):
        query = " ".join(parameters)

        if query == "":
            return await self.play_favorites(message_info.nickname)
        if query == "?":
            return await self.play_radar(message_info.nickname)
        return await self.play_song(query, message_info.nickname)

    async def _play(self, request: PlaybackRequest):
        result = await self.controller.play_song.execute(request)
        return result.as_response()

    async def play_song(self, music_query, requester=None):
        """`:play <歌名> [歌手]` —— 单曲点播。"""
        return await self._play(PlaybackRequest.song(music_query, requester=requester))

    async def play_favorites(self, requester=None):
        """`:play ""` —— 播放全部收藏。"""
        return await self._play(PlaybackRequest.favorites(requester=requester))

    async def play_radar(self, requester=None):
        """`:play ?` —— 打开雷达电台。"""
        return await self._play(PlaybackRequest.radar(requester=requester))
