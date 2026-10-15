from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.playback.models import PlaybackMode, PlaybackRequest


class PlaylistCommand(BaseCommand):
    """`:playlist <query>` 切到某个歌单；裸 `:playlist` 查询当前队列。

    两条路径的语义不同，因此共用一个命令类，但只有一条参与播放静音：

    - **带查询词** —— 一次真正的切歌，交给 `MusicManager.play()`：守护、静音、
      房间同步都由引擎流水线负责，命令层不再自己守护、自己采纳。
    - **不带查询词** —— 纯读取当前播放队列。不切歌、不采纳、不碰麦克风。

    Elements 与选择器一律来自 `config.yaml` 的 `qq_music.elements`；歌单搜索、
    点卡片、播放全部等 UI 编排归 `QQMusicUIDriver`（见 `playback/`）。
    """

    playback_muting = True
    handler_attr = 'music_handler'

    def playback_muting_applies(self, parameters) -> bool:
        """只有带查询词的那条路径参与命令级闭麦。

        带参数时这条路径已迁进 `MusicManager.play()`，由引擎在守护通过之后自己
        闭麦；命令级闭麦发生在守护之前，只会让「被守护拒绝的那一次」也响一次
        无来由的静音（见 `BaseCommand.playback_muting_applies`）。

        不带参数是纯查询：一个字都不该被切，也不该占用麦克风。
        """
        return bool(parameters) and bool(getattr(self, "playback_muting", False))

    async def do_process(self, message_info, parameters):
        if not parameters:
            # 只读路径：直接读队列，不构造播放请求、不进引擎。
            return self.handler.get_playlist_info()

        result = await self.music_manager.play(
            # 直接构造而非 `PlaybackRequest.playlist(...)`：`playlist` 已是该数据类
            # 的字段（写进房间的 `current_playlist_name`），同名 classmethod 会顶掉
            # 字段的类级默认值，让 `request.playlist` 变成一个绑定方法。
            PlaybackRequest(
                mode=PlaybackMode.PLAYLIST,
                query=' '.join(parameters),
                requester=message_info.nickname,
            )
        )
        return result.as_response()
