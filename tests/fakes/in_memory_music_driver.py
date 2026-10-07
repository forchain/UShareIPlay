"""In-memory QQ Music UI driver —— 端口的离线替身。

播放流水线的三处外部依赖在这里全部被换掉：

| 真实依赖 | 替身 |
|---|---|
| Appium UI（查歌、切 tab、点播放全部） | `InMemoryMusicUIDriver`，按模式返回脚本化结果 |
| MediaSession 就绪（`dumpsys media_session`） | 测试模块内的 `_ReadinessProbe`，无需睡眠即可判定就绪 |
| 麦克风 UI（`MicManager`） | 测试模块内的 `_RecordingMicManager`，记录真实发生的开闭麦动作 |

因此「守护拒绝时一个 UI 动作都不该发生」「切歌前必先闭麦」这类断言，
考的是引擎自己做的决策，而不是任何 UI 时序。
"""

from ushareiplay.managers.playback.driver import MusicUIDriverPort
from ushareiplay.managers.playback.models import (
    PlaybackOutcome,
    PlaybackRequest,
    PlaybackTrack,
)


class InMemoryMusicUIDriver(MusicUIDriverPort):
    """按模式返回脚本化结果的 UI 端口替身。

    Args:
        tracks: 模式 → 该模式下 UI 解析出的曲目。未列出的模式回落到
            `_synthesized_track`，用请求自己的查询词/频道拼出可辨识的曲目。
        failures: 模式 → 失败原因。列出的模式一律 `ok=False`。
        topics: 模式 → UI 上读到的房间话题。未列出的模式回落到队列行。
        titles: 模式 → UI 上读到的房间标题。未列出时沿用请求的 `room_title`。
        playlists: 模式 → UI 上读到的完整歌单名。未列出时沿用请求的 `playlist`。
        journal: 可选的共享事件流。填入后每次驱动 UI 会追加 `"ui:<模式>"`，
            用来与麦克风的开闭麦事件交错断言「先闭麦、再动 UI、最后开麦」。

    Attributes:
        requests: 引擎驱动过的请求，按顺序记录。被守护拒绝的请求不会出现在这里。
    """

    def __init__(self, tracks=None, failures=None, topics=None, titles=None, playlists=None, journal=None):
        self.tracks = dict(tracks or {})
        self.failures = dict(failures or {})
        self.topics = dict(topics or {})
        self.titles = dict(titles or {})
        self.playlists = dict(playlists or {})
        self.journal = journal
        self.requests = []

    def start_playback(self, request: PlaybackRequest) -> PlaybackOutcome:
        self.requests.append(request)
        if self.journal is not None:
            self.journal.append(f"ui:{request.mode.value}")

        failure = self.failures.get(request.mode)
        if failure:
            return PlaybackOutcome.failed(failure)

        track = self.tracks.get(request.mode) or self._synthesized_track(request)
        return PlaybackOutcome.started(
            track,
            title=self.titles.get(request.mode),
            topic=self.topics.get(request.mode),
            playlist=self.playlists.get(request.mode),
        )

    @staticmethod
    def _synthesized_track(request: PlaybackRequest) -> PlaybackTrack:
        """没有脚本时，用请求本身造出可辨识的曲目。

        让「测试没配 track 就静默返回空歌名」不可能发生 —— 那会让断言变得
        空洞（任何 `started` 都成立）。
        """
        subject = (request.query or request.channel or request.mode.value).strip()
        return PlaybackTrack(song=subject, singer=f"{request.mode.value}-歌手", album="")