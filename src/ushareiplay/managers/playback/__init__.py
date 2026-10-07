"""深度播放引擎的契约层：请求/结果模型与 UI 驱动端口。

命令层只需要知道两件事：构造一个 `PlaybackRequest`，从 `PlaybackResult` 读结果。
Appium 细节、守护规则、静音生命周期与房间同步都在 `MusicManager.play()` 内部。
"""

from ushareiplay.managers.playback.driver import MusicUIDriverPort
from ushareiplay.managers.playback.models import (
    PlaybackMode,
    PlaybackOutcome,
    PlaybackRequest,
    PlaybackResult,
    PlaybackStatus,
    PlaybackTrack,
)

__all__ = [
    "MusicUIDriverPort",
    "PlaybackMode",
    "PlaybackOutcome",
    "PlaybackRequest",
    "PlaybackResult",
    "PlaybackStatus",
    "PlaybackTrack",
]