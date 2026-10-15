from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.models import (
    PlaybackRequest,
    PlaybackVariant,
)


class FavCommand(BaseCommand):
    """`:fav` —— 收藏的三个入口，统一走 `MusicManager.play()`。

    命令层只做一件事：把用户敲的子命令翻成播放请求。进收藏页、筛选、收藏内搜索、
    点播放全部、读歌单、回首页这些 UI 动作全在 `QQMusicUIDriver` 里，房间标题/话题/
    歌单的同步也归引擎的标准流水线（`playlist_adoption.adopt`），因此这里既没有
    守护调用也没有 `playback_muting`：

    - 守护：`MusicManager.play()` 第一段就问 `guard_switch(requester)`，命令再问一遍
      等于同一件事跑两遍，还会丢掉带 `config=` 的那次判定。
    - 静音：引擎在守护通过之后才闭麦（ADR-0007）。命令级闭麦发生在守护之前，被守护
      拒绝的切歌也会在房间里响一次无来由的静音。
    """

    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        """处理 fav 命令
        参数:
            无参数: 直接播放所有收藏
            两个参数及以上(第一个为 0 或 type, 其余为分类关键字): 筛选后播放
            两个参数及以上(第一个为 2 或 search, 其余为关键字): 收藏内搜索并播放搜索结果列表
        """
        if len(parameters) == 0:
            # 无参数，直接播放所有收藏
            return await self._play(
                PlaybackRequest.favorites(requester=message_info.nickname)
            )

        # 有参数：第一个参数为子命令，其余为参数内容（允许带空格）
        subcmd = str(parameters[0]).lower()
        arg = ' '.join(parameters[1:]).strip()
        if not arg:
            return {'error': '参数错误，使用方式: :fav 或 :fav type 关键字 或 :fav 2 关键字'}

        if subcmd in ['0', 'type']:
            return await self._play(
                PlaybackRequest.favorites(
                    arg,
                    variant=PlaybackVariant.FILTER,
                    requester=message_info.nickname,
                )
            )

        if subcmd in ['2', 'search']:
            return await self._play(
                PlaybackRequest.favorites(
                    arg,
                    variant=PlaybackVariant.SEARCH,
                    requester=message_info.nickname,
                )
            )

        return {'error': f'第一个参数必须是 0/type 或 2/search，当前为: {parameters[0]}'}

    @staticmethod
    async def _play(request):
        """把请求交给引擎，并取回命令层的老 dict 形状。

        回复里 `{playlist}` 放的是这次播出的歌单全文（迁移前 `:fav` 就是这么回的），
        驱动把它放进了 `extra`；房间广播的站名则走 `outcome.playlist`。两者内容不同，
        不是同一个字段。
        """
        result = await MusicManager.instance().play(request)
        return result.as_response()
