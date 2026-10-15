from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.playback.models import PlaybackMode, PlaybackRequest


class AlbumCommand(BaseCommand):
    """`:album [query]` —— 播某张专辑；不带参数时播「现在这首所在的专辑」。

    整条编排交给 `MusicManager.play()`：搜专辑、切专辑分类、点专辑卡、点「播放
    全部」、读队列都在 `QQMusicUIDriver`（见 `playback/`），守护、静音与房间同步
    由引擎的同一条流水线负责。

    空查询词原样递进去：由驱动读当前播放再拼成 QQ Music 认得的检索词。命令层若
    自己读一次播放信息，同一次播放就会被读两遍，而那份「现在在放什么」在两次
    读取之间随时可能已经变了。

    因此本命令不再声明 `playback_muting`，也没有 `playback_muting_applies()`：
    命令级闭麦发生在守护之前，被守护拒绝的切歌也会在房间里响一次无来由的静音
    （ADR-0007 把闭麦的边界定在真正的切歌过程上，那正是引擎守卫管的事）。

    Elements 与选择器一律来自 `config.yaml` 的 `qq_music.elements`。
    """

    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        result = await self.music_manager.play(
            # 直接构造而非 `PlaybackRequest.album(...)`：构造器名一旦与本数据类
            # 的字段同名就会顶掉字段的类级默认值，让 `request.<字段>` 变成一个
            # 绑定方法。专辑只需要「模式 + 查询词 + 请求者」三样。
            PlaybackRequest(
                mode=PlaybackMode.ALBUM,
                query=' '.join(parameters),
                requester=message_info.nickname,
            )
        )
        return result.as_response()
