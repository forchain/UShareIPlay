"""生产 `QQMusicUIDriver` —— `MusicUIDriverPort` 的 QQ Music 适配器。

放在 `playback/qq_music_ui_driver.py` 而不是 `playback/driver.py`，是为了守住
`driver.py` 的导入纯净：端口模块被 `MusicManager` 与全部测试直接导入，一旦它
顶层引入 `QQMusicHandler`（而后者经 `MusicManager.instance()` 反向依赖
`music_manager`），就形成 `driver → handler → music_manager → driver` 的循环引用，
与 ADR-0009 §4 已经为 `PlaybackMuting` 解开的那个环同型。拆成独立模块后，
本模块的依赖方向是单向的 `qq_music_ui_driver → driver → models`。

同样地，`QQMusicHandler` 由组合根构造注入，本模块不 import 它 —— 依赖倒置到
调用方，测试因此能直接喂一个内存替身，无需 Appium 或真机。
"""

import logging

from ushareiplay.managers.playback.driver import MusicUIDriverPort
from ushareiplay.managers.playback.models import (
    PlaybackMode,
    PlaybackOutcome,
    PlaybackRequest,
    PlaybackTrack,
)


class QQMusicUIDriver(MusicUIDriverPort):
    """把 QQ Music 的 UI 编排关在端口后面。

    Args:
        handler: 已初始化的 `QQMusicHandler`。只读使用，不持有其生命周期 ——
            handler 由 `AppController` 负责构造与注册。
    """

    def __init__(self, handler):
        self._handler = handler
        self.logger = getattr(handler, "logger", None) or logging.getLogger(
            "QQMusicUIDriver"
        )

    def start_playback(self, request: PlaybackRequest) -> PlaybackOutcome:
        """按 `request.mode` 编排 QQ Music 的 UI 并返回观察到的结果。

        实现只读模式与查询词：请求者身份属于引擎的守护职责，不该出现在 UI 层
        （见 `MusicUIDriverPort.start_playback` 的约定）。
        """
        if request.mode is not PlaybackMode.SONG:
            # #425/#431/#434/#437 各自交付一种模式。未实现就响亮失败 ——
            # 静默返回一个空的成功会让引擎去采纳一条房间里并不存在的歌单。
            return PlaybackOutcome.failed(
                f"暂不支持的播放模式：{request.mode.value}"
            )
        return self._play_song(request.query)

    def _play_song(self, query: str) -> PlaybackOutcome:
        """`:play <query>` 的 UI 编排：查歌 → 点第一首 → 收藏 → 质量过滤。

        这里不再等待播放就绪：就绪校验属于引擎（`MusicManager.play()` 经
        `PlaybackMuting.guard` 轮询 MediaSession）。驱动再等一次只会把同一次
        等待变成两遍，并让「搜不到歌」这类快速失败也背上就绪超时的延迟。

        Returns:
            成功为 `PlaybackOutcome.started(track)`，失败一律以返回值汇报 ——
            引擎据此跳过就绪等待并立即恢复开麦。
        """
        handler = self._handler
        try:
            playing_info = handler._prepare_music_playback(query)
        except Exception as exc:
            # 带上原始原因：Appium 的失败原因（会话断开、控件不可交互……）互相之间
            # 完全不同，只报「搜索失败」会让线上问题无从区分。
            self.logger.warning(f"搜索歌曲失败: {query}: {exc}")
            return PlaybackOutcome.failed(f"Failed to query music: {query}: {exc}")

        if not isinstance(playing_info, dict):
            return PlaybackOutcome.failed(f"not found with query {query}")
        if "error" in playing_info:
            return PlaybackOutcome.failed(playing_info["error"])

        song_element = handler.element_finder.wait_for_element_clickable("first_song")
        if not song_element:
            return PlaybackOutcome.failed("Failed to find first song")
        song_element.click()
        self.logger.info(f"Select first song for query: {query}")

        # 播放页会自动弹出：未收藏则自动收藏，否则下次点播搜不到这首歌
        handler.ensure_favorited_in_playing_page(timeout=10)

        # 老歌过滤要在播放刚起来时立刻判一次（与迁移前的命令层同一时机）。
        # 它会就地往曲目 dict 上补发行日期，因此必须在判定之后才读 extra。
        self._quality_check(playing_info)

        return PlaybackOutcome.started(
            PlaybackTrack(
                song=playing_info.get("song", ""),
                singer=playing_info.get("singer", ""),
                album=playing_info.get("album", ""),
            ),
            extra=self._response_extra(playing_info),
        )

    @staticmethod
    def _response_extra(playing_info: dict) -> dict:
        """挑出老歌过滤补上的回复字段。

        只搬运确实拿到的值：空的发行日期会被 `command_manager` 的 `setdefault`
        填成 `""`，提前塞一个 None 反而会让模板渲染出字面量 "None"。
        """
        release_date = (playing_info.get("release_date") or "").strip()
        return {"release_date": release_date} if release_date else {}

    def _quality_check(self, playing_info: dict) -> None:
        """把解析出的曲目交给老歌过滤；失败不应阻断播放本身。"""
        try:
            from ushareiplay.managers.music_manager import MusicManager

            MusicManager.instance().handle_song_quality_check(playing_info)
        except Exception as exc:
            self.logger.warning(f"歌曲质量检查失败: {exc}")

