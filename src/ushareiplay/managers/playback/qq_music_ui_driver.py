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
import time
from html import unescape

from appium.webdriver.common.appiumby import AppiumBy

from ushareiplay.helpers.playlist_info import get_playlist_text_and_first_song
from ushareiplay.helpers.playlist_parser import PlaylistParser
from ushareiplay.managers.playback.driver import MusicUIDriverPort
from ushareiplay.managers.playback.models import (
    ACCOMPANIMENT_DISABLED_ERROR,
    NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR,
    PLAY_MODE_NAMES,
    AccompanimentOutcome,
    LyricsOutcome,
    PlaybackMode,
    PlayModeOutcome,
    PlaybackOutcome,
    PlaybackRequest,
    PlaybackTrack,
)
from ushareiplay.managers.playback.player_page import (
    ACCOMPANIMENT_MENU_CONTAINER_KEY,
    ACCOMPANIMENT_MENU_KEY,
    ACCOMPANIMENT_MORE_ENTRY_KEY,
    ACCOMPANIMENT_ON_PAGE_KEYS,
    ACCOMPANIMENT_STATE_KEYS,
    ACCOMPANIMENT_SWITCH_KEY,
    ACCOMPANIMENT_TEXT_ON_KEY,
    PLAY_MODE_ELEMENT_KEYS,
    ensure_player_page,
)

# 切到歌词分类后等页面重排的秒数。取自迁移前 LyricsCommand 的既有等待。
LYRICS_TAB_SETTLE_SECONDS = 0.2

# 歌单搜索结果页上「这是歌单卡片」与「搜了个空」的区别点（config.yaml 的
# qq_music.elements）。合成一个列表而不是各判各的：任一先出现即停，避免先等满
# 一个元素的超时再等第二个。
PLAYLIST_RESULT_KEYS = ["playlist_result", "not_found"]

# 「播放全部」在不同版本/不同页面下有三套文案，因此走三 key 兜底。
PLAY_ALL_KEYS = ["play_all", "play_all_playlist", "play_all_compact"]

# 歌单详情页第一行（歌名/歌手）按列拆开读：列容器与列内文字都是原生控件，没有
# 独立 resource-id，只能按类名逐列取。
LINEAR_LAYOUT_CLASS = "android.widget.LinearLayout"
TEXT_VIEW_CLASS = "android.widget.TextView"

# 播放页元素 key → 模式 key。与 `player_page` 里的私有映射同向，但驱动要自己
# 反查点击后的模式，因此这里按公开常量重新推导，不去 import 对方的下划线名字。
_MODE_KEY_BY_ELEMENT_KEY = {
    element_key: mode_key for mode_key, element_key in PLAY_MODE_ELEMENT_KEYS.items()
}


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
        if request.mode is PlaybackMode.SONG:
            return self._play_song(request.query)
        if request.mode is PlaybackMode.PLAYLIST:
            return self._play_playlist(request.query)
        # #425/#431/#437 各自交付其余模式。未实现就响亮失败 ——
        # 静默返回一个空的成功会让引擎去采纳一条房间里并不存在的歌单。
        return PlaybackOutcome.failed(f"暂不支持的播放模式：{request.mode.value}")

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

    # ------------------------------------------------------------------
    # 歌单播放（#434）
    # ------------------------------------------------------------------

    def _play_playlist(self, query: str) -> PlaybackOutcome:
        """`:playlist <query>` 的 UI 编排：搜歌单 → 点开 → 播放全部 → 读队列。

        与单曲点播不同，这条编排的产物是**一个列表**而不是一首歌：房间标题与话题
        来自歌单卡片上的名字（`PlaylistParser` 按 `｜`/方括号/破折号…的优先级拆
        成主副标题），完整歌单名写进 `current_playlist_name`，而给用户看的回复是
        点完「播放全部」之后队列里真正的歌。

        这里同样不等播放就绪 —— 那件事归引擎（`MusicManager.play()` 经
        `PlaybackMuting.guard` 轮询 MediaSession）。

        Returns:
            成功为 `PlaybackOutcome.started(...)`；失败一律以返回值汇报。
        """
        try:
            return self._run_playlist_flow(query)
        except Exception as exc:
            # 带上原始原因：Appium 的失败原因（会话断开、控件不可交互……）互相之间
            # 完全不同，只报「歌单播放失败」会让线上问题无从区分。
            self.logger.warning(f"播放歌单失败: {query}: {exc}")
            return PlaybackOutcome.failed(f"Failed to play playlist: {query}: {exc}")

    def _run_playlist_flow(self, query: str) -> PlaybackOutcome:
        handler = self._handler

        if not handler.query_music(query):
            self.logger.warning("Failed to query music in playlist")
            return PlaybackOutcome.failed("Failed to query music playlist")

        if not self._select_category_tab("playlist"):
            self.logger.warning("Failed to find playlist tab")
            return PlaybackOutcome.failed("Failed to find playlist tab")
        self.logger.info("Selected playlist tab")

        result_key, result = handler.element_finder.wait_for_any_element(
            PLAYLIST_RESULT_KEYS
        )
        if not result_key or result_key == "not_found" or not result:
            self.logger.warning(f"Failed to find playlist result with query {query}")
            return PlaybackOutcome.failed(f"Failed to find playlist with query {query}")

        result.click()
        self.logger.info("Selected playlist result")

        # 歌单名先整份留住：解析只用来切房名/话题，写进房间的「当前歌单」必须是
        # 卡片上的原文，拆过之后就再也拼不回去了。
        playlist_name = result.text or ""
        subject, topic = PlaylistParser().parse_playlist_name(playlist_name)
        song_name, singer_name = self._read_first_track()

        # 解析不出主副标题时退回歌单里的第一行：宁可让房间显示一句歌名/歌手，
        # 也不要留下一个空标题 —— 空标题会让房间沿用上一首歌单的话题。
        if not subject:
            self.logger.warning("Failed to parse playlist name")
            subject = singer_name
        if not topic:
            topic = song_name

        _, play_button = handler.element_finder.wait_for_any_element(PLAY_ALL_KEYS)
        if not play_button:
            self.logger.warning("Failed to find play all button (album or playlist)")
            return PlaybackOutcome.failed("Failed to find play all button")

        play_button.click()
        self.logger.info("Selected play all button")

        return PlaybackOutcome.started(
            PlaybackTrack(song=song_name, singer=singer_name),
            title=subject,
            topic=topic,
            playlist=playlist_name,
            extra={"playlist": self._read_queue_text(fallback=playlist_name)},
        )

    def _read_first_track(self) -> tuple:
        """读歌单详情页第一行的（歌名, 歌手）。

        两者都是可有可无的兜底来源，因此这一段任何一步读不出来都退化成空串，
        不让一个可选的补充信息变成整条歌单播放的失败。

        Returns:
            `(歌名, 歌手)`，任一读不到时该位为空串。
        """
        try:
            item = self._handler.element_finder.try_find_element("result_item")
            if not item:
                return "", ""
            rows = item.find_elements(AppiumBy.CLASS_NAME, LINEAR_LAYOUT_CLASS)
            if not rows:
                return "", ""
            song = self._read_cell_text(rows[0])
            singer = self._read_cell_text(rows[1]) if len(rows) > 1 else ""
            return song, singer
        except Exception as exc:
            self.logger.warning(f"读取歌单第一行失败: {exc}")
            return "", ""

    @staticmethod
    def _read_cell_text(row) -> str:
        """取一列里的文字；列内没有 TextView 时如实回空串。"""
        try:
            cell = row.find_element(AppiumBy.CLASS_NAME, TEXT_VIEW_CLASS)
            return (cell.text or "").strip()
        except Exception:
            return ""

    def _read_queue_text(self, fallback: str) -> str:
        """读点完「播放全部」之后的播放队列，作为给用户的回复正文。

        读不到队列不是失败：歌已经在放了，把失败报给用户会让人以为歌没响。因此
        退回歌单名，并按 warning 记一笔（与迁移前命令层的同一时刻、同一兜底）。

        Args:
            fallback: 队列读不出来时改用的歌单名。

        Returns:
            队列文本，或兜底的 `fallback`。
        """
        playlist_text, _, error = get_playlist_text_and_first_song(
            self._handler.get_playlist_info()
        )
        if error:
            self.logger.warning(
                f"Failed to read playlist after playback started: {error}"
            )
            return fallback
        return playlist_text

    @staticmethod
    def _select_category_tab(tab_name: str) -> bool:
        """切到搜索结果的分类页。tab 选择是 `MusicManager` 上的既有委派，不重写一遍。

        与 `_select_lyrics_tab` 同样在函数体内 import：`music_manager` 顶层会 import
        本模块，静态 import 会形成 `driver → music_manager → driver` 的循环引用
        （模块 docstring 里那个环同型）。
        """
        try:
            from ushareiplay.managers.music_manager import MusicManager

            return bool(MusicManager.instance().select_tab(tab_name))
        except Exception as exc:
            logging.getLogger("QQMusicUIDriver").warning(f"切换{tab_name}分类失败: {exc}")
            return False

    # ------------------------------------------------------------------
    # 播放模式切换（#423）
    # ------------------------------------------------------------------

    def set_play_mode(self, target_mode: str) -> PlayModeOutcome:
        """切到 `target_mode` 并返回播放页上真正点亮的那一档。

        参数归一化与「已经在目标模式就别动 UI」的短路都在
        `MusicManager.set_play_mode()` 里；这里只负责播放页的实际动作。
        """
        try:
            return self._switch_play_mode(target_mode)
        except Exception as exc:
            # 端口约定：UI 层失败一律以返回值汇报。让异常冲出这里，
            # 调用方只会看到一个没有本地化说明的 AttributeError。
            self.logger.warning(f"切换播放模式失败: {target_mode}: {exc}")
            return PlayModeOutcome.failed(f"切换模式失败: {exc}")

    def _switch_play_mode(self, target_mode: str) -> PlayModeOutcome:
        handler = self._handler
        entry = ensure_player_page(handler, logger=self.logger)
        if not entry.ok:
            return PlayModeOutcome.failed(entry.error)

        observed = entry.mode_key
        self._note_play_mode(observed, reason="mode_ui_detect")

        if observed == target_mode:
            return PlayModeOutcome.switched(target_mode, already_target=True)

        element_key = PLAY_MODE_ELEMENT_KEYS[target_mode]
        mode_keys = list(PLAY_MODE_ELEMENT_KEYS.values())

        # 最多点两次：模式按钮的第一次点击有时落在切页动画上，没切过去。
        # 每次点击后都重读播放页 —— 只有重读才知道到底切没切，不能凭「点了就当成了」。
        for attempt in range(2):
            if not handler.gesture_handler.click_element_at(entry.element):
                self.logger.warning(
                    f"切换播放模式第 {attempt + 1} 次点击未生效，继续重试"
                )
            else:
                found_key, found_element = handler.element_finder.wait_for_any_element(mode_keys)
                if not found_key or not found_element:
                    self.logger.warning("切换后未找到播放模式元素，继续重试")
                else:
                    observed = _MODE_KEY_BY_ELEMENT_KEY.get(found_key, "unknown")
                    self._note_play_mode(observed, reason="mode_ui_detect_after_click")
                    if observed == target_mode:
                        return PlayModeOutcome.switched(target_mode)

        return PlayModeOutcome.failed(
            f"FAIL: 无法切换到目标模式，请检查播放状态"
            f"（target={PLAY_MODE_NAMES.get(target_mode, target_mode)}, "
            f"actual={PLAY_MODE_NAMES.get(observed, observed)}）",
            mode=observed,
        )

    def _note_play_mode(self, mode_key: str, reason: str) -> None:
        """把播放页上观察到的模式写回 handler 缓存；写失败不该阻断切换本身。"""
        if not mode_key or mode_key == "unknown":
            return
        note = getattr(self._handler, "note_play_mode", None)
        if note is not None:
            note(mode_key, reason)
        else:
            setattr(self._handler, "play_mode_key", mode_key)

    # ------------------------------------------------------------------
    # 伴奏开关（#427）
    # ------------------------------------------------------------------

    def set_accompaniment(self, enable: bool) -> AccompanimentOutcome:
        """把伴唱开关拨到 `enable`，返回播放页上最终的开合状态。

        参数归一化在 `MusicManager.set_accompaniment()` 里；这里只负责播放页上的
        实际动作。两条 UI 通路 —— 播放页上直接有开关，或 K歌入口只在「更多」菜单
        里、得滚动着找 —— 都关在这一个端口方法后面，调用方看到的是同一个结果。
        """
        try:
            return self._switch_accompaniment(enable)
        except Exception as exc:
            # 端口约定：UI 层失败一律以返回值汇报。
            self.logger.warning(f"切换伴奏模式失败: {enable}: {exc}")
            return AccompanimentOutcome.failed(f"切换伴奏模式失败: {exc}")

    def _switch_accompaniment(self, enable: bool) -> AccompanimentOutcome:
        handler = self._handler
        entry = ensure_player_page(
            handler,
            logger=self.logger,
            on_page_keys=ACCOMPANIMENT_ON_PAGE_KEYS,
            no_music_error=NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR,
        )
        if not entry.ok:
            return AccompanimentOutcome.failed(entry.error)

        if entry.element_key == ACCOMPANIMENT_MORE_ENTRY_KEY:
            return self._toggle_accompaniment_via_menu(entry.element, enable)
        return self._toggle_accompaniment_direct(entry.element_key, entry.element, enable)

    def _toggle_accompaniment_direct(
        self, element_key: str, element, enable: bool
    ) -> AccompanimentOutcome:
        """播放页上直接显示伴唱状态：点那行文案即切换。

        Args:
            element_key: 认出的那个文案 key（`accompaniment_text_on`/`_off`），
                当前开关状态就由它决定。
            element: 该文案元素，点它即切换。
            enable: 目标状态。

        Returns:
            `AccompanimentOutcome.switched(enable)`；本来就是目标状态时
            `already_target=True` 且一个点击都不发生。
        """
        current = element_key == ACCOMPANIMENT_TEXT_ON_KEY
        if current == enable:
            # 页上本来就是这个状态：不点，也不留「切换成功」的痕迹。
            return AccompanimentOutcome.switched(current, already_target=True)

        if not self._handler.gesture_handler.click_element_at(element):
            return AccompanimentOutcome.failed(
                f"Failed to {'enable' if enable else 'disable'} accompaniment mode",
                enabled=current,
            )
        self.logger.info(f"{'Enabled' if enable else 'Disabled'} accompaniment mode")
        return AccompanimentOutcome.switched(enable)

    def _toggle_accompaniment_via_menu(self, more_entry, enable: bool) -> AccompanimentOutcome:
        """K歌入口只在「更多」菜单里：进菜单、滚动找到菜单项、点开、再拨开关。

        这一条通路比页上直接开关多三步导航，元素 key 全部来自
        `config.yaml` 的 `qq_music.elements`（本模块只出现 key、不出现 XPath）。
        """
        handler = self._handler

        # K歌入口整体灰掉说明伴奏模式压根没被激活，此时无从开关。
        switch = handler.element_finder.try_find_element(ACCOMPANIMENT_SWITCH_KEY)
        if switch is not None and switch.get_attribute("enabled") == "false":
            return AccompanimentOutcome.failed(ACCOMPANIMENT_DISABLED_ERROR)

        self.logger.info("找到伴奏更多菜单入口，进入伴奏设置")
        if not handler.gesture_handler.click_element_at(more_entry):
            return AccompanimentOutcome.failed("Failed to click accompaniment switch")

        # 菜单项在滚动列表里未必露脸，滚到它为止。
        _, menu_item, _ = handler.gesture_handler.scroll_container_until_element(
            ACCOMPANIMENT_MENU_KEY, ACCOMPANIMENT_MENU_CONTAINER_KEY
        )
        if menu_item is None:
            return AccompanimentOutcome.failed("Failed to find accompaniment menu")
        menu_item.click()
        self.logger.info("已点开伴奏菜单")

        state_key, state_button = handler.element_finder.wait_for_any_element(
            list(ACCOMPANIMENT_STATE_KEYS)
        )
        if not state_button:
            return AccompanimentOutcome.failed("Failed to find accompaniment menu")

        current = state_key == "accompaniment_button_on"
        if current != enable:
            if not handler.gesture_handler.click_element_at(state_button):
                return AccompanimentOutcome.failed(
                    "Failed to toggle accompaniment state", enabled=current
                )
            self.logger.info(
                f"Toggled accompaniment state to {'on' if enable else 'off'}"
            )
        # 菜单是盖在播放页上的弹层：不按返回键会一直挡着后面的 UI。
        handler.key_actions.press_back()

        return AccompanimentOutcome.switched(enable, already_target=current == enable)

    # ------------------------------------------------------------------
    # 歌词查询（#430）
    # ------------------------------------------------------------------

    def query_lyrics(self, query: str) -> LyricsOutcome:
        """查 `query` 的歌词原文。

        刻意**不**复用 `ensure_player_page()`：那是播放页的进入仪式（按返回键 +
        认 `playing_bar`/模式按钮），而歌词走的是搜索结果的分类页，按返回键只会
        退回上一页；「现在没在放歌」对按搜索取歌词也不是前提。歌词只需要
        「切前台」这一个公共前置动作。
        """
        try:
            return self._query_lyrics(query)
        except Exception as exc:
            self.logger.warning(f"查询歌词失败: {query}: {exc}")
            return LyricsOutcome.failed(f"Failed to query lyrics: {exc}")

    def _query_lyrics(self, query: str) -> LyricsOutcome:
        handler = self._handler
        if not handler.key_actions.switch_to_app():
            return LyricsOutcome.failed("Failed to switch to music app")

        if not handler.query_music(query):
            return LyricsOutcome.failed(f'Failed to find song matching "{query}"')

        if not self._select_category_tab("lyrics"):
            return LyricsOutcome.failed("Failed to select lyrics tab")

        # 切 tab 后页面要重排，等分类结果稳定再读歌词
        time.sleep(LYRICS_TAB_SETTLE_SECONDS)

        key, element = handler.element_finder.wait_for_any_element(["lyrics_text", "not_found"])
        if not key or key == "not_found" or not element:
            return LyricsOutcome.failed(f'No lyrics found for "{query}"')

        element.click()
        return LyricsOutcome.found(unescape(element.text or ""))

    def _quality_check(self, playing_info: dict) -> None:
        """把解析出的曲目交给老歌过滤；失败不应阻断播放本身。"""
        try:
            from ushareiplay.managers.music_manager import MusicManager

            MusicManager.instance().handle_song_quality_check(playing_info)
        except Exception as exc:
            self.logger.warning(f"歌曲质量检查失败: {exc}")

