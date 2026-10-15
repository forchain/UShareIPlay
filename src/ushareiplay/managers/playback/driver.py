"""内部端口：播放相关的低层 UI 动作。

端口与适配器的分工（ADR-0009 的构造注入约定在本模块的体现）：

    MusicManager.play()        引擎：守护 → 静音 → 驱动 → 房间同步
        └── MusicUIDriverPort  端口：Appium 细节止步于此
              ├── QQMusicUIDriver        生产：包装 QQMusicHandler 的 UI 编排
              └── InMemoryMusicUIDriver  测试：内存替身，pytest 离线可跑

端口声明的是「UI 侧需要做且只有 UI 侧知道怎么做」的动作，每种播放模式共用同一个
`start_playback` —— 查歌、切分类 tab、点结果、点播放全部、读队列行都是该动作内部
的实现细节，不必为它们各开一个方法。

切换播放模式（#423）是另一个动作，因此端口从「只有一个方法」变成两个：

    start_playback(request)  一次播放意图的 UI 编排
    set_play_mode(target)    播放模式的切换与当前模式读取

判断该不该进第二个方法的界线是：这件事换一套 UI（别的音乐 App、假的内存替身）要不要
换一份实现？要，就属于端口；不要，就属于方法内部。加播放模式、加队列操作会继续变宽，
这是有意的 —— 收窄端口换来的是「命令层能离线测」，代价只是适配器多写几个方法。
"""

from abc import ABC, abstractmethod

from ushareiplay.managers.playback.models import (
    PlayModeOutcome,
    PlaybackOutcome,
    PlaybackRequest,
)


class MusicUIDriverPort(ABC):
    """把 QQ Music 的 UI 编排关在接口之后。"""

    @abstractmethod
    def start_playback(self, request: PlaybackRequest) -> PlaybackOutcome:
        """按 `request.mode` 走完该模式的 UI 编排，返回观察到的结果。

        Args:
            request: 播放意图；实现只读模式、查询词与频道，不读请求者身份
                （身份判定属于引擎的守护职责，不应出现在 UI 层）。

        Returns:
            成功为 `PlaybackOutcome.started(...)`，失败为
            `PlaybackOutcome.failed(<本地化原因>)`。实现不应抛出 UI 层异常：
            引擎需要据此决定是否跳过播放就绪等待并立即恢复开麦。
        """

    @abstractmethod
    def set_play_mode(self, target_mode: str) -> PlayModeOutcome:
        """切到 `target_mode` 并返回 UI 上实际点亮的模式。

        实现方自己负责的前置动作：确保站在播放页上（见
        `ushareiplay.managers.playback.player_page.ensure_player_page`）、点模式按钮、
        重读按钮状态确认真的切过去了。命令层看不到这些，也不该看到。

        Args:
            target_mode: `PLAY_MODE_BY_INDEX` 的值之一 —— `list`/`single`/`random`。
                参数校验与归一化由 `MusicManager.set_play_mode()` 完成，实现只管执行。

        Returns:
            `PlayModeOutcome.switched(mode)`；进入播放页后发现本来就是目标模式时
            用 `already_target=True`。没有音乐在放、或点不动，返回
            `PlayModeOutcome.failed(<本地化原因>)`。不应抛出 UI 层异常。
        """
