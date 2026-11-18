"""播放出站端口：音乐 UI 驱动、MediaSession 就绪探测、下一首入队、房间档案同步与麦克风依赖。"""

from abc import ABC, abstractmethod
from typing import Optional

from ushareiplay.modules.mic.ports import MicControl
from ushareiplay.modules.playback.domain import (
    AccompanimentOutcome,
    LyricsOutcome,
    PlayModeOutcome,
    PlaybackOutcome,
    PlaybackRequest,
)


class MusicUIDriverPort(ABC):
    """把 QQ Music 的 UI 编排关在接口之后。"""

    @abstractmethod
    def start_playback(self, request: PlaybackRequest) -> PlaybackOutcome:
        """按 `request.mode` 走完该模式的 UI 编排，返回观察到的结果。"""

    @abstractmethod
    def set_play_mode(self, target_mode: str) -> PlayModeOutcome:
        """切到 `target_mode` 并返回 UI 上实际点亮的模式。"""

    @abstractmethod
    def set_accompaniment(self, enable: bool) -> AccompanimentOutcome:
        """把伴唱开关拨到 `enable` 并返回 UI 上最终的开合状态。"""

    @abstractmethod
    def query_lyrics(self, query: str) -> LyricsOutcome:
        """查 `query` 的歌词原文并交出来。"""


class MediaSessionPort(ABC):
    """OS 级 MediaSession 读取、就绪等待与切歌按键端口。"""

    @abstractmethod
    def get_playback_info(self) -> dict:
        """读取当前播放元数据与状态。"""

    @abstractmethod
    def wait_for_playback_ready(
        self,
        expected_song: Optional[str] = None,
        timeout: float = 5.0,
        settling_delay: float = 0.3,
    ) -> bool:
        """等待底层播放就绪（state=Playing 且可选校验目标曲目）。"""

    @abstractmethod
    def skip_song(self) -> dict:
        """跳过当前歌曲并返回切歌前的曲目信息。"""


class NextTrackPort(ABC):
    """`:next` 下一首入队的 UI 端口。"""

    @abstractmethod
    def play_next(self, query: str) -> dict:
        """把歌曲追加到「下一首播放」。"""


class PlaybackControlPort(ABC):
    """系统级播放控制端口（暂停/恢复与媒体音量）。"""

    @abstractmethod
    def pause_resume(self, should_pause: bool) -> dict:
        """暂停或恢复播放。"""

    @abstractmethod
    def get_volume_level(self) -> Optional[int]:
        """读取当前媒体音量（0~15）；读取失败返回 None。"""

    @abstractmethod
    def step_volume(self, delta: int) -> None:
        """按步长增减媒体音量（正数调大，负数调小）。"""


class RoomProfileWriter(ABC):
    """歌单采纳后同步房间标题与话题的出站端口。"""

    @abstractmethod
    def set_title(self, title: str, theme: Optional[str] = None, requester: Optional[str] = None) -> dict:
        """更新房间标题。"""

    @abstractmethod
    def set_topic(self, topic: str, requester: Optional[str] = None) -> dict:
        """更新房间话题。"""


__all__ = [
    "MediaSessionPort",
    "MicControl",
    "MusicUIDriverPort",
    "NextTrackPort",
    "PlaybackControlPort",
    "RoomProfileWriter",
]
