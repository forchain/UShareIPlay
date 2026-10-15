from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.models import PlaybackRequest


class PlayCommand(BaseCommand):
    """`:play` —— 点歌、播放全部收藏、打开雷达电台。

    三条分支都交给 `MusicManager.play()`：查歌与点歌的 UI 编排在
    `QQMusicUIDriver`，守护、静音与房间同步在引擎的同一条流水线上。

    因此本命令不再声明 `playback_muting`，也没有 `playback_muting_applies()`：
    命令级闭麦发生在守护之前，被守护拒绝的切歌也会在房间里响一次无来由的静音
    （ADR-0007 把闭麦的边界定在真正的切歌过程上，那正是引擎守卫管的事）。
    """

    handler_attr = 'music_handler'

    def playback_expected_song(self, parameters):
        query = ' '.join(parameters or [])
        if not query or query == '?':
            return None
        return query

    async def do_process(self, message_info, parameters):
        query = ' '.join(parameters)

        if query == '':
            return await self.play_favorites(message_info.nickname)
        elif query == '?':
            return await self.play_radar(message_info.nickname)
        else:
            return await self.play_song(query, message_info.nickname)

    @staticmethod
    async def _play(request):
        result = await MusicManager.instance().play(request)
        return result.as_response()

    async def play_song(self, music_query, requester=None):
        """`:play <歌名> [歌手]` —— 单曲点播。

        查歌、点结果、收藏、质量过滤都由 `QQMusicUIDriver` 在引擎的静音守护内
        完成；命令层只负责把请求翻译成 `PlaybackRequest`，再把结果交给公屏模板。
        """
        return await self._play(PlaybackRequest.song(music_query, requester=requester))

    async def play_favorites(self, requester=None):
        """`:play ""` —— 播放全部收藏（`:fav` 是它的同义写法）。"""
        return await self._play(PlaybackRequest.favorites(requester=requester))

    async def play_radar(self, requester=None):
        """`:play ?` —— 打开雷达电台。"""
        return await self._play(PlaybackRequest.radar(requester=requester))
