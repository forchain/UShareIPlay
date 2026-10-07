"""内部端口：播放相关的低层 UI 动作。

端口与适配器的分工（ADR-0009 的构造注入约定在本模块的体现）：

    MusicManager.play()        引擎：守护 → 静音 → 驱动 → 房间同步
        └── MusicUIDriverPort  端口：Appium 细节止步于此
              ├── QQMusicUIDriver        生产：包装 QQMusicHandler 的 UI 编排
              └── InMemoryMusicUIDriver  测试：内存替身，pytest 离线可跑

端口只声明「按请求完成一次 UI 编排」这一个动作。查歌、切分类 tab、点结果、
点播放全部、读队列行都是该动作内部的实现细节，因此每种播放模式共用同一个端口方法 ——
新增播放模式不应该让端口变宽。
"""

from abc import ABC, abstractmethod

from ushareiplay.managers.playback.models import PlaybackOutcome, PlaybackRequest


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