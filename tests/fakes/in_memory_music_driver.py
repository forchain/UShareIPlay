"""In-memory QQ Music UI driver —— 端口的离线替身。

播放流水线的三处外部依赖在这里全部被换掉：

| 真实依赖 | 替身 |
|---|---|
| Appium UI（查歌、切 tab、点播放全部、切换播放模式、读歌词） | `InMemoryMusicUIDriver`，按模式/查询词返回脚本化结果 |
| MediaSession 就绪（`dumpsys media_session`） | 测试模块内的 `_ReadinessProbe`，无需睡眠即可判定就绪 |
| 麦克风 UI（`MicManager`） | 测试模块内的 `_RecordingMicManager`，记录真实发生的开闭麦动作 |

因此「守护拒绝时一个 UI 动作都不该发生」「切歌前必先闭麦」这类断言，
考的是引擎自己做的决策，而不是任何 UI 时序。
"""

from ushareiplay.managers.playback.driver import MusicUIDriverPort
from ushareiplay.managers.playback.models import (
    ACCOMPANIMENT_DISABLED_ERROR,
    NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR,
    NO_PLAYING_MUSIC_ERROR,
    PLAY_MODE_NAMES,
    AccompanimentOutcome,
    LyricsOutcome,
    PlayModeOutcome,
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
            切换播放模式时追加 `"mode:<目标模式>"`，伴唱开关时追加
            `"acc:on"`/`"acc:off"`，用来与麦克风的开闭麦事件交错断言顺序。
        play_mode: 播放页上当前点亮的播放模式 key（#423）。默认 `list`。
        no_music: 没有音乐在放 —— 模式切换与伴奏开关都据此报「没有在放」。
        play_mode_failures: 目标模式 → 该次切换的失败原因，用于注入错误。
        stuck_play_mode: 点击模式按钮不改变模式（模拟切换没生效、重试耗尽）。
        accompaniment: UI 上当前伴唱开关的状态（#427）。默认 `False`（原唱）。
        accompaniment_path: 替身冒充的是哪条 UI 通路 —— `direct`（播放页上直接
            有开关）或 `more_menu`（要进「更多」菜单才找得到）。替身是状态机，
            不真的滚菜单；这个旋钮只用于断言「走的是哪条路」。
        accompaniment_failures: 目标状态 → 该次拨动的失败原因，用于注入错误。
        accompaniment_disabled: K歌入口整体灰掉，伴奏无从开关。
        stuck_accompaniment: 点了开关但状态没变（模拟点击没生效）。
        lyrics: 查询词 → 该词命中的歌词原文（#430）。未列出的查询词回落到
            `_synthesized_lyrics`，让「忘了配歌词」不会静默变成一条空歌词。
        lyrics_failures: 查询词 → 该次取歌词的失败原因，用于注入错误。
        not_found_lyrics: 任何查询都取不到歌词（模拟搜得到歌、却翻不到歌词）。

    Attributes:
        requests: 引擎驱动过的请求，按顺序记录。被守护拒绝的请求不会出现在这里。
        play_mode: 当前点亮着的模式 key，会随成功的切换改变。
        play_mode_requests: 每次 `set_play_mode()` 的目标 key，按顺序记录。
        play_mode_clicks: 真正点过模式按钮的次数（本来就在目标模式时不点）。
        accompaniment_requests: 每次 `set_accompaniment()` 的目标状态，按顺序记录。
        accompaniment_clicks: 真正点过伴奏开关的次数（本来就在目标状态时不点）。
        accompaniment_paths: 每次拨动走的通路，按顺序记录。
        lyrics_requests: 每次 `query_lyrics()` 的查询词，按顺序记录。
    """

    def __init__(
        self,
        tracks=None,
        failures=None,
        topics=None,
        titles=None,
        playlists=None,
        journal=None,
        play_mode="list",
        no_music=False,
        play_mode_failures=None,
        stuck_play_mode=False,
        accompaniment=False,
        accompaniment_path="direct",
        accompaniment_failures=None,
        accompaniment_disabled=False,
        stuck_accompaniment=False,
        lyrics=None,
        lyrics_failures=None,
        not_found_lyrics=False,
    ):
        self.tracks = dict(tracks or {})
        self.failures = dict(failures or {})
        self.topics = dict(topics or {})
        self.titles = dict(titles or {})
        self.playlists = dict(playlists or {})
        self.journal = journal
        self.requests = []

        self.play_mode = play_mode
        self.no_music = no_music
        self.play_mode_failures = dict(play_mode_failures or {})
        self.stuck_play_mode = stuck_play_mode
        self.play_mode_requests = []
        self.play_mode_clicks = 0

        self.accompaniment = accompaniment
        self.accompaniment_path = accompaniment_path
        self.accompaniment_failures = dict(accompaniment_failures or {})
        self.accompaniment_disabled = accompaniment_disabled
        self.stuck_accompaniment = stuck_accompaniment
        self.accompaniment_requests = []
        self.accompaniment_clicks = 0
        self.accompaniment_paths = []

        self.lyrics = dict(lyrics or {})
        self.lyrics_failures = dict(lyrics_failures or {})
        self.not_found_lyrics = not_found_lyrics
        self.lyrics_requests = []

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

    def set_play_mode(self, target_mode: str) -> PlayModeOutcome:
        """脚本化的播放模式切换：状态留在替身上，失败按注入的脚本走。"""
        self.play_mode_requests.append(target_mode)
        if self.journal is not None:
            self.journal.append(f"mode:{target_mode}")

        if self.no_music:
            return PlayModeOutcome.failed(NO_PLAYING_MUSIC_ERROR)
        if target_mode in self.play_mode_failures:
            return PlayModeOutcome.failed(self.play_mode_failures[target_mode])

        if self.play_mode == target_mode:
            # 播放页上本来就是这一档：没有点击发生。
            return PlayModeOutcome.switched(self.play_mode, already_target=True)

        self.play_mode_clicks += 1
        if self.stuck_play_mode:
            return PlayModeOutcome.failed(
                f"FAIL: 无法切换到目标模式，请检查播放状态"
                f"（target={PLAY_MODE_NAMES.get(target_mode, target_mode)}, "
                f"actual={PLAY_MODE_NAMES.get(self.play_mode, self.play_mode)}）",
                mode=self.play_mode,
            )

        self.play_mode = target_mode
        return PlayModeOutcome.switched(self.play_mode)

    def query_lyrics(self, query: str) -> LyricsOutcome:
        """脚本化的取歌词：查过什么、翻没翻到，都留在替身上可断言。"""
        self.lyrics_requests.append(query)
        if self.journal is not None:
            self.journal.append(f"lyrics:{query}")

        failure = self.lyrics_failures.get(query)
        if failure:
            return LyricsOutcome.failed(failure)

        if self.not_found_lyrics:
            return LyricsOutcome.failed(f'No lyrics found for "{query}"')

        text = self.lyrics.get(query)
        if text is None:
            text = self._synthesized_lyrics(query)
        if not text:
            return LyricsOutcome.failed(f'No lyrics found for "{query}"')
        return LyricsOutcome.found(text)

    @staticmethod
    def _synthesized_lyrics(query: str) -> str:
        """没有脚本时，用查询词本身造出可辨识的歌词。

        让「测试没配歌词就静默返回空文本」不可能发生 —— 那会让断言变得空洞
        （任何 `ok=True` 都成立）。
        """
        return f"（{query} 的歌词）"

    def set_accompaniment(self, enable: bool) -> AccompanimentOutcome:
        """脚本化的伴奏开关：状态留在替身上，失败按注入的脚本走。"""
        self.accompaniment_requests.append(enable)
        self.accompaniment_paths.append(self.accompaniment_path)
        if self.journal is not None:
            self.journal.append(f"acc:{'on' if enable else 'off'}")

        if self.no_music:
            return AccompanimentOutcome.failed(NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR)
        if self.accompaniment_disabled:
            return AccompanimentOutcome.failed(ACCOMPANIMENT_DISABLED_ERROR)
        if enable in self.accompaniment_failures:
            return AccompanimentOutcome.failed(
                self.accompaniment_failures[enable], enabled=self.accompaniment
            )

        if self.accompaniment == enable:
            # 页上本来就是这个状态：没有点击发生。
            return AccompanimentOutcome.switched(self.accompaniment, already_target=True)

        self.accompaniment_clicks += 1
        if self.stuck_accompaniment:
            return AccompanimentOutcome.failed(
                "FAIL: 伴奏开关点击后状态未变化", enabled=self.accompaniment
            )

        self.accompaniment = enable
        return AccompanimentOutcome.switched(self.accompaniment)

    @staticmethod
    def _synthesized_track(request: PlaybackRequest) -> PlaybackTrack:
        """没有脚本时，用请求本身造出可辨识的曲目。

        让「测试没配 track 就静默返回空歌名」不可能发生 —— 那会让断言变得
        空洞（任何 `started` 都成立）。
        """
        subject = (request.query or request.channel or request.mode.value).strip()
        return PlaybackTrack(song=subject, singer=f"{request.mode.value}-歌手", album="")