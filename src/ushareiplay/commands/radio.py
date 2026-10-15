from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.playback.models import PlaybackMode, PlaybackRequest


class RadioCommand(BaseCommand):
    """`:radio [channel]` —— 打开 QQ 音乐的电台频道，统一走 `MusicManager.play()`。

    命令层只做一件事：把用户敲的子命令翻成播放请求。进首页、找频道入口、点播放、
    读队列这些 UI 动作全在 `QQMusicUIDriver` 里（见 `playback/`），老歌过滤走
    `MusicManager` 的统一歌曲质量检查，房间标题/话题/歌单的同步也归引擎流水线
    （`playlist_adoption.adopt`），因此这里既没有守护调用也没有 `playback_muting`：

    - 守护：`MusicManager.play()` 第一段就问 `guard_switch(requester)`，命令再问一遍
      等于同一件事跑两遍，还会丢掉带 `config=` 的那次判定。
    - 静音：引擎在守护通过之后才闭麦（ADR-0007）。命令级闭麦发生在守护之前，被守护
      拒绝的切歌也会在房间里响一次无来由的静音。

    Elements 与选择器一律来自 `config.yaml` 的 `qq_music.elements`。
    """

    handler_attr = 'music_handler'

    # 频道词表。裸 `:radio` 落到 `collection`（精选），这是迁移前的既有默认。
    RADIO_CHANNELS = ('guess', 'daily', 'collection', 'sleep', 'radar')
    DEFAULT_CHANNEL = 'collection'

    async def do_process(self, message_info, parameters):
        channel = str(parameters[0]).lower() if parameters else self.DEFAULT_CHANNEL
        if channel not in self.RADIO_CHANNELS:
            return {'error': f"Unsupported radio keyword: {channel}"}

        result = await self.music_manager.play(
            # 直接构造而非 `PlaybackRequest.radio(...)`：本类只需要一个按频道
            # 取值的入口，不必为此再往 `models.py` 里加一个构造器。
            PlaybackRequest(
                mode=PlaybackMode.RADIO,
                channel=channel,
                requester=message_info.nickname,
            )
        )
        return result.as_response()
