"""内部端口：播放相关的低层 UI 动作。

端口与适配器的分工（ADR-0009 的构造注入约定在本模块的体现）：

    MusicManager.play()        引擎：守护 → 静音 → 驱动 → 房间同步
        └── MusicUIDriverPort  端口：Appium 细节止步于此
              ├── QQMusicUIDriver        生产：包装 QQMusicHandler 的 UI 编排
              └── InMemoryMusicUIDriver  测试：内存替身，pytest 离线可跑

端口声明的是「UI 侧需要做且只有 UI 侧知道怎么做」的动作，每种播放模式共用同一个
`start_playback` —— 查歌、切分类 tab、点结果、点播放全部、读队列行都是该动作内部
的实现细节，不必为它们各开一个方法。

切换播放模式（#423）是另一个动作，因此端口从「只有一个方法」变成两个；伴奏开关
（#427）同理再加一个：

    start_playback(request)  一次播放意图的 UI 编排
    set_play_mode(target)    播放模式的切换与当前模式读取
    set_accompaniment(on)    伴唱开关的拨动与最终状态读取

取歌词（#430）是另一个动作。歌词来自「搜一首歌 → 点歌词 tab → 读结果」这条
搜索链路，因此它的 UI 编排与上面三条都不同：

    query_lyrics(query)      查歌、选歌词 tab、读 DOM 文字并解开 HTML 实体

判断该不该进新方法的界线是：这件事换一套 UI（别的音乐 App、假的内存替身）要不要
换一份实现？要，就属于端口；不要，就属于方法内部。加队列操作会继续变宽，
这是有意的 —— 收窄端口换来的是「命令层能离线测」，代价只是适配器多写几个方法。
"""

from abc import ABC, abstractmethod

from ushareiplay.managers.playback.models import (
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

    @abstractmethod
    def set_accompaniment(self, enable: bool) -> AccompanimentOutcome:
        """把伴唱开关拨到 `enable` 并返回 UI 上最终的开合状态。

        实现方自己负责的前置与分支：确保站在播放页上（见
        `ushareiplay.managers.playback.player_page.ensure_player_page`）、认出走的是
        哪条路（播放页上直接开关，还是「更多」菜单里滚动出来的菜单项）、必要时
        开合、再读一次确认真的拨过去了。命令层看不到这些，也不该看到。

        Args:
            enable: `True` 开、伴唱（伴奏），`False` 关、回到原唱。参数校验与
                归一化由 `MusicManager.set_accompaniment()` 完成，实现只管执行。

        Returns:
            `AccompanimentOutcome.switched(enable)`；进播放页后发现本来就是目标状态时
            用 `already_target=True`。没有音乐在放、K歌入口灰掉、或点不动，返回
            `AccompanimentOutcome.failed(<本地化原因>)`。不应抛出 UI 层异常。
        """

    @abstractmethod
    def query_lyrics(self, query: str) -> LyricsOutcome:
        """查 `query` 的歌词原文并交出来。

        实现方自己负责的前置动作：把 QQ Music 拉到前台、执行搜索、用
        `MusicManager.instance().select_tab("lyrics")` 选到歌词分类、点开结果项、
        读 DOM 文字并 `html.unescape` 解开 HTML 实体。命令层看不到这些，也不该看到。

        注意实现**不要**复用
        `ushareiplay.managers.playback.player_page.ensure_player_page`：那是播放页
        的进入仪式（按返回键 + 认 `playing_bar`/模式按钮），而歌词走的是搜索结果的
        分类页，按返回键只会退回上一页；而且「现在没在放歌」对按搜索取歌词并不是
        前提，用播放页那套探测反而会给出误导性的错误。歌词只需要「切前台」这一个
        公共前置动作。

        Args:
            query: 搜索词。查询词兜底（无参数时问当前正在放的这首）由
                `MusicManager.query_lyrics()` 完成，实现只管按词执行。

        Returns:
            取到为 `LyricsOutcome.found(<歌词原文>)`；搜不到、切不到歌词 tab 或
            读不出文字时为 `LyricsOutcome.failed(<原因>)`。不应抛出 UI 层异常 ——
            「没有歌词」是正常结局，要让命令层据此回复房间而不是崩掉。
        """
