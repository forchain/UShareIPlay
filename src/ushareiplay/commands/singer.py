from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.playback.models import PlaybackMode, PlaybackRequest


class SingerCommand(BaseCommand):
    """`:singer <query>` —— 播某个歌手的歌。

    整条编排交给 `MusicManager.play()`：搜歌手、首页快捷键或歌手分类兜底、点
    「播放全部」、读队列都在 `QQMusicUIDriver`（见 `playback/`），守护、静音与
    房间同步由引擎的同一条流水线负责。

    因此本命令不再声明 `playback_muting`，也没有 `playback_muting_applies()`：
    命令级闭麦发生在守护之前，被守护拒绝的切歌也会在房间里响一次无来由的静音
    （ADR-0007 把闭麦的边界定在真正的切歌过程上，那正是引擎守卫管的事）。

    Elements 与选择器一律来自 `config.yaml` 的 `qq_music.elements`。
    """

    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        result = await self.music_manager.play(
            # 直接构造而非 `PlaybackRequest.singer(...)`：构造器名一旦与本数据类
            # 的字段同名就会顶掉字段的类级默认值，让 `request.<字段>` 变成一个
            # 绑定方法。歌手/专辑只需要「模式 + 查询词 + 请求者」三样。
            PlaybackRequest(
                mode=PlaybackMode.SINGER,
                query=' '.join(parameters),
                requester=message_info.nickname,
            )
        )
        return result.as_response()
