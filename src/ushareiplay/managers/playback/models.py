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
from types import MappingProxyType
from typing import Any, Mapping, Optional

_EMPTY_EXTRA: Mapping[str, Any] = MappingProxyType({})


def _freeze_extra(extra: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """把回复用的附加字段收成只读映射。

    冻结 dataclass 只挡住属性重绑，挡不住 `result.extra["x"] = ...` 这种就地修改 ——
    而这份 extra 会一路流到用户看到的公屏文案上，就地改写会让「这次回复的内容」
    不再由这一次播放决定。
    """
    if not extra:
        return _EMPTY_EXTRA
    return MappingProxyType(dict(extra))


# 播放模式的词表：命令参数 ↔ 记录在案的 key ↔ 面向用户的名称。
# 三处（:mode 命令、MusicManager、QQMusicHandler 的缓存）共用这一份定义，
# 免得「参数怎么写」和「房间里怎么显示」各说各话。
PLAY_MODE_BY_INDEX = {0: "list", 1: "single", -1: "random"}
PLAY_MODE_INDEX_BY_KEY = {"list": 0, "single": 1, "random": -1}
PLAY_MODE_NAMES = {
    "list": "顺序播放",
    "single": "单曲循环",
    "random": "随机播放",
    "unknown": "未知",
}

# 没有音乐在放时统一回给用户的那句话（`ModeCommand` 的用户可见契约之一）。
NO_PLAYING_MUSIC_ERROR = "现在没有播放音乐，无法切换模式"
# `:mode` 参数既不是 0/1/-1 时的那句（命令层与 MusicManager 共用同一份文案）。
PLAY_MODE_INVALID_PARAMETER_ERROR = "Invalid mode parameter, must be 0, 1 or -1"

# 伴奏开关（#427）的用户可见契约文案。与上面那句刻意不同：这是迁移前就存在的
# 英文原文，房间里的人一直读到它，改字等于改掉既有的用户可见行为。
NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR = "No music playing, cannot toggle accompaniment mode"
# K歌入口整体灰掉时的那句：伴奏模式压根没被激活，无从开关。
ACCOMPANIMENT_DISABLED_ERROR = "Accompaniment mode is disabled"
# `:acc` 参数既不是 1 也不是 0 时的那句。
ACCOMPANIMENT_INVALID_PARAMETER_ERROR = "Invalid accompaniment parameter, must be 1 or 0"


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


class PlaybackVariant(str, Enum):
    """同一种播放模式内部的几种取法（#425）。

    模式说的是「要播什么」，形态说的是「怎么取」。收藏页有三条差别很大的 UI 通路 ——
    全部播放、筛选后播放、收藏内搜索后播放 —— 它们是同一种模式下的不同取法，不是三种
    模式：把收藏拆成三个模式会让 `list_mode` 里出现房间从未有过的取值。
    """

    ALL = "all"
    FILTER = "filter"
    SEARCH = "search"


@dataclass(frozen=True)
class PlaybackRequest:
    """一次播放意图。

    Attributes:
        mode: 播放模式，决定驱动端口走哪条 UI 编排。
        query: 搜索词（单曲点播、歌单、歌手、专辑都用它）。收藏形态下是筛选关键字
            或搜索词 —— 调用方给的字面量，页面标题由驱动观察后回填。
        variant: 模式内部的取法，目前只有 FAVORITES 有多形态（见 `PlaybackVariant`）。
            关键字仍走 `query`，形态只回答「这些字怎么用」。
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
    variant: Optional[PlaybackVariant] = None

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

    @classmethod
    def favorites(
        cls,
        query=None,
        *,
        variant: PlaybackVariant = PlaybackVariant.ALL,
        requester=None,
        **kwargs,
    ) -> "PlaybackRequest":
        """`:fav` / `:play ""` —— 收藏（#425）。

        Args:
            query: 筛选关键字（`:fav type 粤语`）或搜索词（`:fav search 谢安琪`）。
                全部播放时留空。
            variant: 三种取法之一。缺省即「播放全部收藏」。
            requester: 触发者，写入房间的 `player_name`。

        房间标题与歌单名不作为参数传进来：粤语在房间里叫「粤音」这类映射是 UI 侧
        才成立的事实，由驱动观察后回填 `PlaybackOutcome.title` / `.playlist`。
        """
        return cls(
            mode=PlaybackMode.FAVORITES,
            query=query,
            variant=variant,
            requester=requester,
            **kwargs,
        )

    @classmethod
    def radar(cls, requester=None, **kwargs) -> "PlaybackRequest":
        """`:play ?` —— 雷达电台流量（#425）。

        雷达只有一种取法，因此不带 `query` / `variant`：要选频道那是 `:radio` 的事
        （RADIO 模式，`#431`），与这里的「打开雷达电台」不是一回事。
        """
        return cls(mode=PlaybackMode.RADAR, requester=requester, **kwargs)


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
        extra: 驱动的回复附加字段（如发行日期）。这些是「只有 UI 层拿得到的事实」，
            由 `MusicManager.play()` 原样转交 `PlaybackResult.as_response()`。
    """

    ok: bool
    track: PlaybackTrack = field(default_factory=PlaybackTrack)
    error: Optional[str] = None
    title: Optional[str] = None
    topic: Optional[str] = None
    playlist: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_EXTRA)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", _freeze_extra(self.extra))

    @classmethod
    def started(
        cls,
        track: PlaybackTrack,
        *,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        playlist: Optional[str] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> "PlaybackOutcome":
        return cls(
            ok=True,
            track=track,
            title=title,
            topic=topic,
            playlist=playlist,
            extra=extra,
        )

    @classmethod
    def failed(cls, error: str) -> "PlaybackOutcome":
        return cls(ok=False, error=error)


@dataclass(frozen=True)
class PlaybackResult:
    """播放请求的最终归宿 —— 引擎返回给命令层的唯一结果类型。

    除状态与曲目外，还携带「回复格式元数据」：命令层的 `response_template`
    各不相同（`:play` 用 `{song} - {singer} • {album} • {release_date}`，
    fav/singer/playlist/radio/album 用 `{playlist}`），把这些键收在这里，
    命令就只管把 `as_response()` 的结果交给 `CommandManager`，不再各自手拼 dict。

    Attributes:
        status: 三种归宿之一。
        track: 已开始的曲目；被拒绝或 UI 失败时为空。
        error: 本地化错误说明。被拒绝与 UI 失败时非空；`STARTED` 时也可能非空 ——
            那表示歌已经在放、但房间同步（标题/话题）失败，此时 `error` 只用于日志，
            不该出现在给用户的回复里。
        playlist: UI 上读到的完整歌单名。为 None 时 `as_response()` 渲染成空串 ——
            不是省略该键（见 `as_response` 的说明）。
        extra: 其余回复字段（如老歌过滤阶段补上的 `release_date`）。
    """

    status: PlaybackStatus
    track: PlaybackTrack = field(default_factory=PlaybackTrack)
    error: Optional[str] = None
    playlist: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_EXTRA)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", _freeze_extra(self.extra))

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

        成功时**恒定**给出 `song` / `singer` / `album` / `playlist` 四个键，再并上
        `extra`；被拒或失败时给 `{'error': ...}`。

        `playlist` 没有就渲染成空串而不是省略 —— `CommandManager` 的
        `response_template.format(**result)` 不在 try/except 里，缺键就是
        `KeyError` 冲出 `process_command`，用户连报错都收不到。fav/singer/
        playlist/radio/album 五个模板恰好是纯 `"{playlist}"`，省略即线上失联。
        """
        if not self.started:
            return {"error": self.error}

        response = {
            "song": self.track.song,
            "singer": self.track.singer,
            "album": self.track.album,
            "playlist": self.playlist or "",
        }
        response.update(self.extra)
        return response


@dataclass(frozen=True)
class PlayModeOutcome:
    """驱动端口切换播放模式后的观察结果（#423）。

    与 `PlaybackOutcome` 分开：切换模式不产生曲目、不换歌，也就不该拖着
    歌名歌手那一整套字段 —— `mode` 是 UI 上真正点亮着的那档模式。

    Attributes:
        ok: UI 编排是否走通（含「本来就已经是目标模式」这种成功）。
        mode: 观察到的当前模式 key（`list`/`single`/`random`）；不知道时为 `unknown`。
            失败时若驱动已经看见了当前模式，也会如实填上，让房间缓存不与 UI 脱节。
        error: 失败原因（本地化），仅 `ok=False` 时有意义。
        already_target: 进入播放页后发现本来就是目标模式 —— 区别于「点了一下才切过去」，
            两者的用户可见措辞不同（「已经是…」vs「成功切换到…」）。
    """

    ok: bool
    mode: str = "unknown"
    error: Optional[str] = None
    already_target: bool = False

    @classmethod
    def switched(cls, mode: str, *, already_target: bool = False) -> "PlayModeOutcome":
        return cls(ok=True, mode=mode, already_target=already_target)

    @classmethod
    def failed(cls, error: str, *, mode: str = "unknown") -> "PlayModeOutcome":
        return cls(ok=False, error=error, mode=mode)


@dataclass(frozen=True)
class LyricsOutcome:
    """驱动端口取回歌词后的观察结果（#430）。

    与 `PlaybackOutcome` / `PlayModeOutcome` 分开：歌词既不产生曲目也不换歌，
    唯一的产物是「读到的歌词原文」—— HTML 实体是否解开、切了哪个 tab、点没点
    结果项，都是 UI 侧的事，不该冒到命令层。

    原文（而非分组后的几段）是有意的：折行宽度与分段条数属于房间里的排版约定，
    随 `config.yaml` 变化，留在命令层才是对的；驱动只负责如实交出读到的文字。

    Attributes:
        ok: 是否取到了歌词。搜不到歌词是 `ok=False` 的正常结局，不是异常。
        text: 歌词原文；`ok=False` 时为空串。
        error: 失败原因（本地化/沿用既有文案），仅 `ok=False` 时有意义。
    """

    ok: bool
    text: str = ""
    error: Optional[str] = None

    @classmethod
    def found(cls, text: str) -> "LyricsOutcome":
        return cls(ok=True, text=text)

    @classmethod
    def failed(cls, error: str) -> "LyricsOutcome":
        return cls(ok=False, error=error)


@dataclass(frozen=True)
class AccompanimentOutcome:
    """驱动端口切换伴唱开关后的观察结果（#427）。

    与 `PlayModeOutcome` 同构，只是观察的对象从「模式 key」换成一个开关：
    伴奏是 on/off，不是一档名字，因此这里存布尔而不是字符串。

    两条 UI 通路（播放页上直接开关、更多菜单里滚动出来的菜单项）都收敛到
    这一种结果 —— 调用方只关心「最后是不是开着」，不关心走的哪条路。

    Attributes:
        ok: UI 编排是否走通（含「本来就已经是目标状态」这种成功）。
        enabled: 观察到的伴唱状态；不知道时为 None。
        error: 失败原因（本地化），仅 `ok=False` 时有意义。
        already_target: 进播放页后发现本来就是目标状态 —— 区别于「点了一下才
            切过去」，前者一个点击都没发生，不该留下「切换成功」的痕迹。
    """

    ok: bool
    enabled: Optional[bool] = None
    error: Optional[str] = None
    already_target: bool = False

    @classmethod
    def switched(cls, enabled: bool, *, already_target: bool = False) -> "AccompanimentOutcome":
        return cls(ok=True, enabled=enabled, already_target=already_target)

    @classmethod
    def failed(cls, error: str, *, enabled: Optional[bool] = None) -> "AccompanimentOutcome":
        return cls(ok=False, error=error, enabled=enabled)

