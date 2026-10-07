"""统一播放请求/结果契约 —— 深度播放引擎的输入输出。

五个音乐命令此前各自拼装 dict 返回值、各自解读「歌名/歌手/标题/话题」，
于是同一次播放在五个文件里有五种形状。这里把形状收敛成两个不可变数据类：

    PlaybackRequest  —— 调用方说什么（模式、查询词、电台频道、请求者、要采纳的标题）
    PlaybackResult   —— 播放之后发生了什么（状态、曲目、或本地化错误）

不可变是有意的：播放是跨多步的异步过程，中间状态一旦可改，「房间最终采纳了什么」
就无从断言。命令层拿到的 `PlaybackResult.as_response()` 仍是旧的 dict 形状，
因此迁移可以逐个命令进行。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PlaybackMode(str, Enum):
    """房间支持的全部播放意图。

    值即写入 `list_mode` 的字符串，与 `PlaylistAdoption.adopt()` 的既有约定一致。
    """

    SONG = "song"
    FAVORITES = "favorites"
    RADAR = "radar"
    PLAYLIST = "playlist"
    SINGER = "singer"
    ALBUM = "album"
    RADIO = "radio"


class PlaybackStatus(str, Enum):
    """一次播放请求的三种归宿。

    `REJECTED` 与 `FAILED` 分开是有意义的：前者是房间规则说「不行」（谁在放），
    后者是 UI 说「做不到」（搜不到歌、按钮缺失）。两者的日志与回复语气都不同。
    """

    STARTED = "started"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class PlaybackRequest:
    """一次播放意图。

    Attributes:
        mode: 播放模式，决定驱动端口走哪条 UI 编排。
        query: 搜索词（单曲点播、歌单、歌手、专辑都用它）。
        channel: 电台频道（daily/guess/sleep/radar/collection），仅 RADIO 模式使用。
        requester: 触发播放的用户名，写入房间的 `player_name`。
        room_title: 要采纳的房间标题（如 "O Station"）；驱动若观察到更准确的值则以其为准。
        playlist: 完整歌单名，写入 `current_playlist_name`。
    """

    mode: PlaybackMode
    query: Optional[str] = None
    channel: Optional[str] = None
    requester: Optional[str] = None
    room_title: Optional[str] = None
    playlist: Optional[str] = None

    @property
    def expected_song(self) -> Optional[str]:
        """播放就绪时要校验的目标曲目。

        只有点播单曲才校验元数据：其余模式的队列内容由调用方无从预知，
        拿查询词去比对 MediaSession 上报的目标曲目必然超时。
        """
        return self.query if self.mode is PlaybackMode.SONG else None

    @classmethod
    def song(cls, query, requester=None, **kwargs) -> "PlaybackRequest":
        """`:play <query>` —— 单曲点播。"""
        return cls(mode=PlaybackMode.SONG, query=query, requester=requester, **kwargs)


@dataclass(frozen=True)
class PlaybackTrack:
    """播放队列里的一行：歌名 / 歌手 / 专辑。"""

    song: str = ""
    singer: str = ""
    album: str = ""

    @property
    def queue_line(self) -> str:
        """播放队列行文本 —— QQ Music 的歌单行形如「歌名 - 歌手」。

        `PlaylistAdoption.primary_topic()` 按 " - " 取前半段作为房间话题，
        所以这里保持同一约定，不要改成裸连字符（见该函数 docstring）。
        """
        if self.song and self.singer:
            return f"{self.song} - {self.singer}"
        return self.song or self.singer or ""


@dataclass(frozen=True)
class PlaybackOutcome:
    """驱动端口的返回值：UI 那边实际发生了什么。

    `title` / `topic` / `playlist` 是「UI 上读到的事实」而非调用方的期望 ——
    只有驱动知道收藏页的标题到底叫什么、当前队列第一行是什么歌。

    Attributes:
        ok: UI 编排是否走通并触发了播放。
        track: 触发播放的曲目。
        error: 失败原因（本地化），仅 `ok=False` 时有意义。
        title: 观察到的房间标题来源；None 表示沿用 `PlaybackRequest.room_title`。
        topic: 观察到的房间话题来源；None 表示由曲目队列行推导。
        playlist: 观察到的完整歌单名；None 表示沿用 `PlaybackRequest.playlist`。
    """

    ok: bool
    track: PlaybackTrack = field(default_factory=PlaybackTrack)
    error: Optional[str] = None
    title: Optional[str] = None
    topic: Optional[str] = None
    playlist: Optional[str] = None

    @classmethod
    def started(
        cls,
        track: PlaybackTrack,
        *,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        playlist: Optional[str] = None,
    ) -> "PlaybackOutcome":
        return cls(ok=True, track=track, title=title, topic=topic, playlist=playlist)

    @classmethod
    def failed(cls, error: str) -> "PlaybackOutcome":
        return cls(ok=False, error=error)


@dataclass(frozen=True)
class PlaybackResult:
    """播放请求的最终归宿 —— 引擎返回给命令层的唯一结果类型。

    Attributes:
        status: 三种归宿之一。
        track: 已开始的曲目；被拒绝或 UI 失败时为空。
        error: 本地化错误说明。被拒绝与 UI 失败时非空；`STARTED` 时也可能非空 ——
            那表示歌已经在放、但房间同步（标题/话题）失败，此时 `error` 只用于日志，
            不该出现在给用户的回复里。
    """

    status: PlaybackStatus
    track: PlaybackTrack = field(default_factory=PlaybackTrack)
    error: Optional[str] = None

    @property
    def started(self) -> bool:
        return self.status is PlaybackStatus.STARTED

    @property
    def rejected(self) -> bool:
        """被房间守护拒绝 —— 回复用户「谁在放」，不是「搜不到歌」。"""
        return self.status is PlaybackStatus.REJECTED

    @property
    def failed(self) -> bool:
        """UI 侧执行失败。"""
        return self.status is PlaybackStatus.FAILED

    def as_response(self) -> dict:
        """命令层的返回形状，与迁移前的 dict 契约一致。

        以 `started` 而非 `error` 为准：歌已经在放而房间同步失败时，房间里的人
        听到的是歌，回复就该是歌。反过来按 `error` 判定会让人在歌响起时读到报错。

        `{'song','singer','album'}` 表示成功、`{'error': ...}` 表示被拒或失败。
        保留这个形状是为了让五个命令能逐个迁移，而不是一次性改掉所有回复文案。
        """
        if self.started:
            return {
                "song": self.track.song,
                "singer": self.track.singer,
                "album": self.track.album,
            }
        return {"error": self.error}