"""播放领域模型与纯规则：请求/结果契约、歌单上下文、Next Queue、歌单守护与静音策略。"""

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.shared.roles import RolePolicy

_EMPTY_EXTRA: Mapping[str, Any] = MappingProxyType({})


def _freeze_extra(extra: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """把回复用的附加字段收成只读映射，防止异步流程中就地篡改。"""
    if not extra:
        return _EMPTY_EXTRA
    return MappingProxyType(dict(extra))


# 播放模式的词表：命令参数 ↔ 记录在案的 key ↔ 面向用户的名称。
PLAY_MODE_BY_INDEX = {0: "list", 1: "single", -1: "random"}
PLAY_MODE_INDEX_BY_KEY = {"list": 0, "single": 1, "random": -1}
PLAY_MODE_NAMES = {
    "list": "顺序播放",
    "single": "单曲循环",
    "random": "随机播放",
    "unknown": "未知",
}

NO_PLAYING_MUSIC_ERROR = "现在没有播放音乐，无法切换模式"
PLAY_MODE_INVALID_PARAMETER_ERROR = "Invalid mode parameter, must be 0, 1 or -1"

NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR = "No music playing, cannot toggle accompaniment mode"
ACCOMPANIMENT_DISABLED_ERROR = "Accompaniment mode is disabled"
ACCOMPANIMENT_INVALID_PARAMETER_ERROR = "Invalid accompaniment parameter, must be 1 or 0"

TOPIC_SEPARATOR = " - "


class PlaybackMode(str, Enum):
    """房间支持的全部播放意图。"""

    SONG = "song"
    FAVORITES = "favorites"
    RADAR = "radar"
    PLAYLIST = "playlist"
    SINGER = "singer"
    ALBUM = "album"
    RADIO = "radio"


UNPROTECTED_PLAYBACK_MODES = frozenset({PlaybackMode.SONG.value})


class PlaybackStatus(str, Enum):
    """一次播放请求的三种归宿。"""

    STARTED = "started"
    REJECTED = "rejected"
    FAILED = "failed"


class PlaybackVariant(str, Enum):
    """同一种播放模式内部的几种取法。"""

    ALL = "all"
    FILTER = "filter"
    SEARCH = "search"


@dataclass(frozen=True)
class PlaybackRequest:
    """一次播放意图。"""

    mode: PlaybackMode
    query: Optional[str] = None
    channel: Optional[str] = None
    requester: Optional[str] = None
    room_title: Optional[str] = None
    playlist: Optional[str] = None
    variant: Optional[PlaybackVariant] = None

    @property
    def expected_song(self) -> Optional[str]:
        """播放就绪时要校验的目标曲目（仅单曲点播校验元数据）。"""
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
        """`:fav` / `:play ""` —— 收藏。"""
        return cls(
            mode=PlaybackMode.FAVORITES,
            query=query,
            variant=variant,
            requester=requester,
            **kwargs,
        )

    @classmethod
    def radar(cls, requester=None, **kwargs) -> "PlaybackRequest":
        """`:play ?` —— 雷达电台流量。"""
        return cls(mode=PlaybackMode.RADAR, requester=requester, **kwargs)


@dataclass(frozen=True)
class PlaybackTrack:
    """播放队列里的一行：歌名 / 歌手 / 专辑。"""

    song: str = ""
    singer: str = ""
    album: str = ""

    @property
    def queue_line(self) -> str:
        """播放队列行文本 —— QQ Music 的歌单行形如「歌名 - 歌手」。"""
        if self.song and self.singer:
            return f"{self.song} - {self.singer}"
        return self.song or self.singer or ""


@dataclass(frozen=True)
class PlaybackOutcome:
    """驱动端口的返回值：UI 那边实际发生了什么。"""

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
    """播放请求的最终归宿 —— 引擎返回给命令层的唯一结果类型。"""

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
        return self.status is PlaybackStatus.REJECTED

    @property
    def failed(self) -> bool:
        return self.status is PlaybackStatus.FAILED

    def as_response(self) -> dict:
        """命令层的返回形状，与迁移前的 dict 契约一致。"""
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
    """驱动端口切换播放模式后的观察结果。"""

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
    """驱动端口取回歌词后的观察结果。"""

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
    """驱动端口切换伴唱开关后的观察结果。"""

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


def primary_topic(text: Optional[str]) -> str:
    """把播放队列行 / 歌曲文案归一化为房间话题（纯函数）。"""
    text = (text or "").strip()
    if not text:
        return ""
    if TOPIC_SEPARATOR in text:
        head = text.split(TOPIC_SEPARATOR)[0].strip()
        if head:
            return head
    return text


def matches_expected_song(reported: Optional[str], expected_song: Optional[str]) -> bool:
    """判断 MediaSession 上报的歌名是否已是本次点播的目标歌曲。"""
    if not expected_song:
        return True
    reported = (reported or "").strip()
    expected = expected_song.strip()
    if not reported:
        return False
    if expected == reported:
        return True
    return bool(set(reported.split()) & set(expected.split()))


@dataclass
class NextQueue:
    """多人 `:next` 累积的待播计数与贡献者集合。"""

    pending_count: int = 0
    contributors: set[str] = field(default_factory=set)

    def record_next(self, requester: str) -> bool:
        """记录一次成功的 :next；返回本次是否从空队列开启。"""
        was_empty = self.pending_count == 0
        self.pending_count += 1
        self.contributors.add(requester)
        return was_empty

    def consume_track(self) -> bool:
        """消费一次曲目切换：待播数 -1（clamp 0），归零时清空贡献者；返回是否刚归零。"""
        if self.pending_count == 0:
            return False
        self.pending_count -= 1
        if self.pending_count == 0:
            self.contributors.clear()
            return True
        return False

    def clear(self) -> bool:
        """清空整个 Next Queue；返回清空前是否非空。"""
        if self.pending_count == 0 and not self.contributors:
            return False
        self.pending_count = 0
        self.contributors.clear()
        return True


@dataclass
class PlaylistContext:
    """房间当前连续队列的状态上下文。"""

    list_mode: str = "unknown"
    player_name: str = "Joyer"
    current_playlist_name: Optional[str] = None
    next_queue: NextQueue = field(default_factory=NextQueue)

    def get_playlist_info(self) -> Optional[dict]:
        """只读歌单视图；没有活跃歌单时返回 None。"""
        if not self.current_playlist_name:
            return None
        return {"type": self.list_mode, "name": self.current_playlist_name}

    def apply_adoption(
        self,
        requester: Optional[str],
        mode: str,
        playlist: Optional[str] = None,
    ) -> bool:
        """把一次已发生的连续歌单切换写入上下文；单曲点播跳过并返回 False。"""
        if mode == PlaybackMode.SONG.value:
            return False
        self.next_queue.clear()
        if requester:
            self.player_name = requester
        self.list_mode = mode
        if playlist is not None:
            self.current_playlist_name = playlist
        return True


class PlaylistGuard:
    """歌单守护纯规则：判断切歌请求是否被当前队列或 Next Queue 阻断。"""

    @staticmethod
    def is_single_song(mode: Optional[str]) -> bool:
        return (mode or "").strip().lower() in UNPROTECTED_PLAYBACK_MODES

    def should_exempt_single_song(
        self,
        requester: str,
        incoming_mode: Optional[str],
        role_policy: RolePolicy,
    ) -> bool:
        """非系统角色的单曲点播不受歌单守护拦。"""
        return self.is_single_song(incoming_mode) and not role_policy.is_system_user(requester)

    @staticmethod
    def check_protection(
        *,
        caller_nickname: str,
        player_name: Optional[str],
        player_avatars: set[str],
        online_users: set[str],
        next_queue: NextQueue,
        contributor_avatars: Mapping[str, set[str]],
        role_policy: RolePolicy,
    ) -> Optional[str]:
        """判定是否阻断切歌；返回错误文案，放行返回 None。"""
        if role_policy.is_human_operator(caller_nickname):
            return None

        if (
            player_name
            and not role_policy.is_privileged(player_name)
            and caller_nickname != player_name
        ):
            if caller_nickname not in player_avatars and bool(player_avatars & online_users):
                return f"{player_name} 正在播放歌单，请等待"

        if next_queue.pending_count <= 0:
            return None

        contributors = sorted(
            c for c in next_queue.contributors if not role_policy.is_privileged(c)
        )
        online_contributor = None
        for contributor in contributors:
            avatars = contributor_avatars.get(contributor, {contributor})
            if caller_nickname in avatars:
                return None
            if online_contributor is None and (avatars & online_users):
                online_contributor = contributor

        if online_contributor:
            return f"{online_contributor} 正在点歌，请等待"
        return None


@dataclass(frozen=True)
class PlaybackMutingSettings:
    """`soul.playback_mute` 配置快照。"""

    enabled: bool = True
    guest_room_only: bool = False
    auto_enable_on_mic: bool = True
    ignore_users: tuple[str, ...] = ()
    timeout: float = 5.0
    settling_delay: float = 0.3

    @classmethod
    def from_config(cls, config: Optional[ConfigView]) -> "PlaybackMutingSettings":
        defaults = cls()
        section = config.maybe_section("playback_mute") if config is not None else None
        if section is None:
            return defaults

        def _val(key: str, default: Any) -> Any:
            v = section.value(key)
            return default if v is None else v

        ignore = _val("ignore_users", defaults.ignore_users)
        return cls(
            enabled=bool(_val("enabled", defaults.enabled)),
            guest_room_only=bool(_val("guest_room_only", defaults.guest_room_only)),
            auto_enable_on_mic=bool(_val("auto_enable_on_mic", defaults.auto_enable_on_mic)),
            ignore_users=tuple(str(name) for name in (ignore or ())),
            timeout=float(_val("timeout", defaults.timeout)),
            settling_delay=float(_val("settling_delay", defaults.settling_delay)),
        )


class PlaybackMutingPolicy:
    """播放静音保护纯策略：常态配置与有人上麦时的运行时开启。"""

    def __init__(self) -> None:
        self._dynamic_enabled = False

    @property
    def dynamically_enabled(self) -> bool:
        return self._dynamic_enabled

    def should_engage(self, settings: PlaybackMutingSettings, *, is_guest_room: bool) -> bool:
        """当前房间是否启用静音保护；运行时开启时无条件生效。"""
        if self._dynamic_enabled:
            return True
        if not settings.enabled:
            return False
        if not settings.guest_room_only:
            return True
        return bool(is_guest_room)

    def enable(self) -> bool:
        """运行时开启静音保护；返回本次调用是否改变了状态。"""
        if self._dynamic_enabled:
            return False
        self._dynamic_enabled = True
        return True

    def arm_on_mic(
        self,
        nickname: str,
        settings: PlaybackMutingSettings,
        *,
        room_owner: Optional[str],
    ) -> bool:
        """有人上麦时的联动判定。"""
        if not settings.auto_enable_on_mic:
            return False
        name = (nickname or "").strip()
        if not name or self._is_ignored(name, settings, room_owner=room_owner):
            return False
        return self.enable()

    def reset(self) -> bool:
        """房间生命周期重置；返回重置前是否处于运行时开启状态。"""
        if not self._dynamic_enabled:
            return False
        self._dynamic_enabled = False
        return True

    @staticmethod
    def _is_ignored(
        nickname: str,
        settings: PlaybackMutingSettings,
        *,
        room_owner: Optional[str],
    ) -> bool:
        normalized = nickname.strip().lower()
        if room_owner and normalized == room_owner.strip().lower():
            return True
        return normalized in {str(name).strip().lower() for name in settings.ignore_users}
