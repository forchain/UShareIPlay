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
import re
import time
from html import unescape
from typing import Callable, Optional

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

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
    PlaybackVariant,
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

# 房间广播名。收藏三种形态共用一个默认站名；筛选/搜索时才按关键字改名。
FAVOURITES_DEFAULT_NAME = "O Station"
RADAR_ROOM_TITLE = "O Radio"

# 电台频道（`PlaybackMode.RADIO`，#431）。裸 `:radio` 落到 `collection`（精选），
# 这是迁移前的既有默认。频道词表本身是命令行文法，权威在
# `RadioCommand.RADIO_CHANNELS`；这里只把 `channel` 分派到各频道的编排。
RADIO_DEFAULT_CHANNEL = "collection"
RADIO_HEALING_ROOM_NAME = "音乐疗愈"
RADIO_RADAR_ROOM_NAME = "O Radio"

# 疗愈在首页 tab 条上的名字与把它滑进视口所需的横滑次数上限。
RADIO_HEALING_TAB_LABEL = "疗愈"
RADIO_HEALING_MAX_SWIPES = 20

# 精选频道首页卡片上「正在播 / 未在播」的两种状态：合成一次 `wait_for_any_element`，
# 任一先出现即停，避免先等满一个元素的超时再等第二个。
RADIO_COLLECTION_STATE_KEYS = ["pause_collection", "play_collection"]

# 精选推荐读歌名时元素失效（频道自己刷新了卡片）就重新找，最多几次。
RADIO_STALE_RETRIES = 3

# 收藏筛选关键字 → 房间标题。粤语/英语用简称，房间名更短。
# 标题与 current_playlist_name 同源，因此只在这里映射一次。
_FAVOURITE_FILTER_TITLES = {
    "粤语": "粤音",
    "英语": "英乐",
}

# 收藏页筛选器里的筛选项与确认按钮，文案都由用户关键字拼出来
# （`TextView[@text="粤语"]` / `确定（12首）`），`config.yaml` 的
# `qq_music.elements` 装不下这种动态文案 —— 元素单一事实源铁律管的是稳定控件，
# 拼出来的文案只能按 XPath 现拼。下面两处是本模块仅有的 raw XPath。
FAVOURITE_CONFIRM_XPATH = (
    '//android.widget.TextView[starts-with(@text,"确定（") and contains(@text,"首）")]'
)
FAVOURITE_COUNT_PATTERN = re.compile(r"确定（(\d+)首）")

# 选完筛选项到确认按钮刷新、确认后回到收藏列表，各等一次页面重排。
FAVOURITE_FILTER_SETTLE_SECONDS = 0.25
FAVOURITE_CONFIRM_SETTLE_SECONDS = 0.35

# 歌单搜索结果页上「这是歌单卡片」与「搜了个空」的区别点（config.yaml 的
# qq_music.elements）。合成一个列表而不是各判各的：任一先出现即停，避免先等满
# 一个元素的超时再等第二个。
PLAYLIST_RESULT_KEYS = ["playlist_result", "not_found"]

# 歌手/专辑的搜索结果页上「这是一条结果」与「搜了个空」的区别点，与歌单同理：
# 合成一个列表而不是各判各的，任一先出现即停。
SINGER_RESULT_KEYS = ["singer_result", "not_found"]
ALBUM_RESULT_KEYS = ["album_result", "not_found"]

# 首页那张「播放歌手: X 的歌曲」的前提是首页歌手区已经排好版。排不出来就只能
# 退回分类页那条路，因此等它只是探路，认出来也不代表就点它。
SINGER_SHORTCUT_KEYS = ["music_tabs", "not_found"]

# 首页快捷键的 `content-desc` 里固定的两段包装：`播放歌手: <歌手名>的歌曲`。
SINGER_CONTENT_DESC_SEPARATOR = ": "
SINGER_CONTENT_DESC_SUFFIX = "的歌曲"

# 歌手名读不出来时房间里也不该出现空白标题，用迁移前就有的 Unknown 顶上。
UNKNOWN_SINGER_NAME = "Unknown"

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


def _singer_name_from_content_desc(content_desc: Optional[str]) -> str:
    """首页歌手卡的 `content-desc` → 歌手名。

    文案形如「播放歌手: 张天赋的歌曲」，由 QQ Music 自己拼：中间那段是歌手名，
    两头是固定包装，拆掉就得到房间该显示的名字。

    拆不出来（文案变了、控件没给属性）时回 Unknown 而不是让异常冒到命令层：
    房名难看只是不好看，卡片照样能点出播放。
    """
    if not content_desc or SINGER_CONTENT_DESC_SEPARATOR not in content_desc:
        return UNKNOWN_SINGER_NAME
    name = content_desc.split(SINGER_CONTENT_DESC_SEPARATOR, 1)[1]
    return name.split(SINGER_CONTENT_DESC_SUFFIX)[0].strip() or UNKNOWN_SINGER_NAME


def favourite_filter_title(keyword: str) -> str:
    """收藏筛选关键字 → 房间标题（也是该歌单的广播名）。

    这个映射跟着「筛选」这个 UI 形态一起搬进驱动：只有驱动知道当前请求走的是筛选，
    命令层不该反过来替 UI 决定房间该叫什么。
    """
    return _FAVOURITE_FILTER_TITLES.get(keyword, keyword or FAVOURITES_DEFAULT_NAME)


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
        if request.mode is PlaybackMode.FAVORITES:
            return self._play_favourites(request)
        if request.mode is PlaybackMode.RADAR:
            return self._play_radar()
        if request.mode is PlaybackMode.PLAYLIST:
            return self._play_playlist(request.query)
        if request.mode is PlaybackMode.RADIO:
            return self._play_radio(request)
        if request.mode is PlaybackMode.SINGER:
            return self._play_singer(request.query)
        if request.mode is PlaybackMode.ALBUM:
            return self._play_album(request.query)
        # 七种播放模式已全部交付（#421/#425/#431/#434/#437）。未实现就响亮失败 ——
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
    # 收藏播放（#425）
    #
    # 收藏有三条 UI 通路：全部播放、筛选后播放、收藏内搜索后播放。三条共用
    # 「进收藏页 → 触发播放 → 读队列 → 回首页」的骨架，只有中间那一步不同 ——
    # 因此形态由 `PlaybackRequest.variant` 决定，骨架只写一遍。
    # ------------------------------------------------------------------

    def _play_favourites(self, request: PlaybackRequest) -> PlaybackOutcome:
        """`:fav` / `:play ""` —— 收藏的三种取法共用一条骨架。"""
        try:
            return self._favourites_flow(request)
        except Exception as exc:
            # 端口约定：UI 层失败一律以返回值汇报，让引擎据此跳过就绪等待并立即恢复开麦。
            self.logger.warning(f"播放收藏失败: {request.variant}: {exc}")
            return PlaybackOutcome.failed(f"Failed to play favourites: {exc}")

    def _favourites_flow(self, request: PlaybackRequest) -> PlaybackOutcome:
        handler = self._handler
        variant = request.variant or PlaybackVariant.ALL

        if not handler.key_actions.switch_to_app():
            return PlaybackOutcome.failed("Cannot switch to qq music")
        self.logger.info("已切到 QQ 音乐，准备进入收藏页")

        entry_error = handler.open_favorites_entry()
        if entry_error:
            return PlaybackOutcome.failed(entry_error.get("error") or "Cannot open favourites")

        count = None
        if variant is PlaybackVariant.SEARCH:
            # 搜索这条路自己点「全部播放」：它要的是搜索结果那一栏的按钮，
            # 而不是收藏页顶部的那个。
            search_error = self._search_within_favourites(request.query or "")
            if search_error:
                return PlaybackOutcome.failed(search_error)
        else:
            if variant is PlaybackVariant.FILTER:
                error, count = self._apply_favourite_filter(request.query or "")
                if error:
                    return PlaybackOutcome.failed(error)
            play_error = self._click_play_all()
            if play_error:
                return PlaybackOutcome.failed(play_error)

        track = self._first_result_track()
        room_name = self._favourites_room_name(variant, request.query)
        playlist_text, first_line, queue_error = get_playlist_text_and_first_song(
            handler.get_playlist_info()
        )
        if queue_error:
            # 歌已经在放了，读不到歌单只该降级、不该把播放收回去。
            self.logger.warning(f"播放已开始但读不到收藏歌单: {queue_error}")
            playlist_text = room_name
            first_line = None

        # 先回 QQ 音乐首页，引擎随后才去 Soul 改标题/话题 —— 顺序反了会让
        # Soul 的弹窗盖在收藏页上。
        handler.navigate_to_home()
        self.logger.info("收藏已开始播放，已回到 QQ 音乐首页，等待引擎同步房间")

        extra = {"playlist": playlist_text}
        if count is not None:
            extra["count"] = count
        return PlaybackOutcome.started(
            track,
            title=room_name,
            topic=self._favourites_topic(variant, request.query, first_line, track),
            playlist=room_name,
            extra=extra,
        )

    def _click_play_all(self) -> Optional[str]:
        """点「全部播放」。返回错误说明；成功为 None。"""
        play_all = self._handler.element_finder.wait_for_element_clickable("play_all")
        if not play_all:
            return "Cannot find play all button"
        play_all.click()
        self.logger.info("已点击「全部播放」")
        return None

    def _first_result_track(self) -> PlaybackTrack:
        """收藏列表首行的歌名/歌手。

        `result_item` 是一行的容器：第 0 个 TextView 是序号或操作按钮，第 1 个是歌名，
        第 2 个是歌手。行还没排版完就少于三个，此时当作读不到，让队列首行顶上。
        """
        result_item = self._handler.element_finder.try_find_element("result_item")
        if not result_item:
            return PlaybackTrack()
        text_views = result_item.find_elements(
            AppiumBy.CLASS_NAME, "android.widget.TextView"
        )
        if len(text_views) < 3:
            return PlaybackTrack()
        return PlaybackTrack(song=text_views[1].text, singer=text_views[2].text)

    @staticmethod
    def _favourites_room_name(
        variant: PlaybackVariant, query: Optional[str]
    ) -> str:
        """这一路收藏在房间里叫什么（同时也是要广播的歌单名）。"""
        if variant is PlaybackVariant.FILTER:
            return favourite_filter_title(query or "")
        if variant is PlaybackVariant.SEARCH:
            return query or FAVOURITES_DEFAULT_NAME
        return FAVOURITES_DEFAULT_NAME

    @staticmethod
    def _favourites_topic(
        variant: PlaybackVariant,
        query: Optional[str],
        first_line: Optional[str],
        track: PlaybackTrack,
    ) -> str:
        """房间话题 = 这次真正开始放的那首歌。

        收藏内搜索是「搜一批、播一批」，话题报歌名即可（迁移前的既有约定：行首的
        `歌名 - 歌手` 只取歌名）；全部播放与筛选则报队列首行，带上歌手更好认。
        """
        if variant is PlaybackVariant.SEARCH:
            if not first_line:
                return query or FAVOURITES_DEFAULT_NAME
            return first_line.split(" - ")[0].strip() or track.song
        return first_line or track.song

    def _apply_favourite_filter(self, keyword: str):
        """新版「筛选歌曲」页：点筛选 → 点关键字 → 点「确定（n首）」。

        Returns:
            `(错误说明, 命中首数)`；成功时错误为 None，首数读不到时为 None。
        """
        filter_favourite = self._handler.element_finder.wait_for_element_clickable(
            "filter_favourite"
        )
        if not filter_favourite:
            return "Cannot find filter button", None
        filter_favourite.click()
        self.logger.info("已打开收藏筛选")

        option = self._xpath_with_stale_retry(
            self._textview_text_xpath(keyword),
            f"Favourite filter option '{keyword}'",
            self._click_element,
        )
        if option is None:
            return f"找不到筛选项: {keyword}", None
        self.logger.info(f"已选择筛选项: {keyword}")

        # 等「确定（n首）」按新的命中数刷新出来再点。
        time.sleep(FAVOURITE_FILTER_SETTLE_SECONDS)

        confirm_text = []

        def _read_then_click(element):
            # 先读文案再点：点下去之后按钮文案可能就变了，首数就再也读不到。
            confirm_text.append((element.text or "").strip())
            element.click()
            return element

        confirm = self._xpath_with_stale_retry(
            FAVOURITE_CONFIRM_XPATH, "Favourite filter confirm button", _read_then_click
        )
        if confirm is None:
            return "Cannot find confirm button: 确定（xxx首）", None
        self.logger.info("已确认收藏筛选条件")

        # 确认后要退回收藏列表，等页面重排再读首行。
        time.sleep(FAVOURITE_CONFIRM_SETTLE_SECONDS)
        matched = FAVOURITE_COUNT_PATTERN.search(confirm_text[0]) if confirm_text else None
        return None, int(matched.group(1)) if matched else None

    def _search_within_favourites(self, keyword: str) -> Optional[str]:
        """收藏页内搜索：滑出搜索框 → 粘关键字 → 点「全部播放」。

        Returns:
            失败时的错误说明；成功为 None。
        """
        handler = self._handler

        play_all = handler.element_finder.wait_for_element_clickable("play_all")
        if not play_all:
            return "Cannot find play all button"

        # 搜索框藏在「全部播放」那一栏的下方：按它的高度往下滚一次才会露脸。
        location = play_all.location
        size = play_all.size
        center_x = int(location["x"] + size["width"] * 0.5)
        center_y = int(location["y"] + size["height"] * 0.5)
        handler.gesture_handler.swipe(
            center_x,
            center_y,
            center_x,
            center_y + max(60, int(size["height"])),
            duration_ms=260,
        )

        search_box = handler.element_finder.wait_for_element_clickable("search_box")
        if not search_box:
            return "Cannot find search box in favourites"
        search_box.click()

        if not handler.element_finder.wait_for_element("favourite_search"):
            return "Cannot find favourite search"

        handler.key_actions.set_clipboard_text(keyword)
        handler.key_actions.paste_text()
        self.logger.info(f"已在收藏内搜索: {keyword}")

        play_search = handler.element_finder.wait_for_element_clickable(
            "play_favourite_search"
        )
        if not play_search:
            return "Cannot find play_favourite_search button"
        play_search.click()
        self.logger.info("已播放收藏内的搜索结果")
        return None

    def _xpath_with_stale_retry(
        self,
        xpath: str,
        description: str,
        handle: Callable,
        timeout: int = 8,
        max_attempts: int = 3,
    ):
        """按 XPath 反复重新定位元素并交给 `handle` 处理，直到处理成功或超时。

        为什么必须重新定位而不是拿一个句柄点到底：筛选项与确认按钮点下去之后页面会
        重排，句柄随即变 stale，拿着旧句柄再点只会静默失败。`handle` 返回值即本方法
        返回值，调用方因此能同时拿到「点没点到」与「点上之后读到了什么」。

        Returns:
            `handle` 的返回值；元素始终找不到则返回 None。
        """
        deadline = time.time() + timeout
        stale_attempts = 0
        while time.time() < deadline:
            try:
                element = self._handler.driver.find_element(AppiumBy.XPATH, xpath)
                if not (element.is_displayed() and element.is_enabled()):
                    time.sleep(0.2)
                    continue
                return handle(element)
            except StaleElementReferenceException:
                stale_attempts += 1
                if stale_attempts >= max_attempts:
                    raise
                self.logger.warning(
                    f"{description} element stale before click, refinding "
                    f"({stale_attempts}/{max_attempts})"
                )
                time.sleep(0.2)
            except NoSuchElementException:
                time.sleep(0.2)
        return None

    @staticmethod
    def _click_element(element):
        """点掉元素并把它交还给调用方 —— `handle` 约定的返回形状。"""
        element.click()
        return element

    @staticmethod
    def _textview_text_xpath(text_value: str) -> str:
        """拼出 `android.widget.TextView[@text=...]` 的 XPath。

        关键字是用户原样输入的，可能带引号 —— 直接塞进双引号属性值会让整条 XPath
        语法失效，因此按 XPath 的转义规则换一种引号，实在都装不下才用 `concat`。
        """
        if '"' not in text_value:
            return f'//android.widget.TextView[@text="{text_value}"]'
        if "'" not in text_value:
            return f"//android.widget.TextView[@text='{text_value}']"
        parts = text_value.split('"')
        concat_parts = []
        for index, part in enumerate(parts):
            if part:
                concat_parts.append(f'"{part}"')
            if index != len(parts) - 1:
                concat_parts.append("'\"'")
        return f"//android.widget.TextView[@text=concat({', '.join(concat_parts)})]"

    # ------------------------------------------------------------------
    # 雷达电台（#425）
    # ------------------------------------------------------------------

    def _play_radar(self) -> PlaybackOutcome:
        """`:play ?` —— 回首页、点开雷达电台，让电台自己开始播。

        与收藏不同：雷达是一路持续流，点进 `radar_nav` 就等于开了播，页面上没有
        「播放全部」可点，所以这里不再读队列 —— 读到的队列是电台的历史列表，不是
        这次要广播的歌单。
        """
        try:
            return self._radar_flow()
        except Exception as exc:
            self.logger.warning(f"打开雷达电台失败: {exc}")
            return PlaybackOutcome.failed(f"Failed to start radar: {exc}")

    def _radar_flow(self) -> PlaybackOutcome:
        handler = self._handler
        if not handler.key_actions.switch_to_app():
            return PlaybackOutcome.failed("Cannot switch to qq music")
        self.logger.info("已切到 QQ 音乐，准备打开雷达电台")

        handler.navigate_to_home()

        radar_nav = handler.element_finder.try_find_element("radar_nav", log=False)
        if not radar_nav:
            return PlaybackOutcome.failed("Cannot find radar_nav")
        radar_nav.click()
        self.logger.info("已进入雷达电台")

        song = handler.element_finder.wait_for_element_clickable("radar_song")
        singer = handler.element_finder.wait_for_element_clickable("radar_singer")
        song_text = song.text if song else "Unknown"
        singer_text = singer.text if singer else "Unknown"

        return PlaybackOutcome.started(
            PlaybackTrack(song=song_text, singer=singer_text),
            title=RADAR_ROOM_TITLE,
            topic=song_text,
        )

    # 电台播放（#431）
    # ------------------------------------------------------------------
    #
    # 五个频道共用「切到 QQ 音乐 → 回首页 → 认出一个频道入口 → 触发播放 →
    # 读队列」的骨架，差别只在首页上认哪个元素、播完之后房间话题取哪段文字。
    # 频道词表是命令行文法，归 `RadioCommand.RADIO_CHANNELS`；这里按
    # `PlaybackRequest.channel` 分派，遇到不认识的一律响亮失败 ——
    # 静默成功会让引擎去采纳一个房间里并不存在的电台。
    # ------------------------------------------------------------------

    def _play_radio(self, request: PlaybackRequest) -> PlaybackOutcome:
        """`:radio [channel]` —— 五种电台共用一条骨架。"""
        try:
            return self._radio_flow(request)
        except Exception as exc:
            # 带上频道名：Appium 的失败原因互相之间完全不同，只报「电台播放失败」
            # 会让线上问题无从区分是哪一路。
            self.logger.warning(f"打开电台失败: {request.channel}: {exc}")
            return PlaybackOutcome.failed(
                f"Failed to start radio {request.channel}: {exc}"
            )

    def _radio_flow(self, request: PlaybackRequest) -> PlaybackOutcome:
        channel = (request.channel or RADIO_DEFAULT_CHANNEL).strip().lower()

        if channel == "guess":
            return self._guess_radio()
        if channel == "daily":
            return self._daily_radio()
        if channel == "collection":
            return self._collection_radio()
        if channel == "sleep":
            return self._sleep_radio()
        if channel == "radar":
            return self._radio_radar()

        self.logger.warning(f"Unknown radio channel: {request.channel}")
        return PlaybackOutcome.failed(f"暂不支持的电台频道：{request.channel}")

    def _switch_to_qq_music_home(self) -> Optional[PlaybackOutcome]:
        """切到 QQ 音乐并回首页。返回非 None 即为失败，调用方直接转交。"""
        handler = self._handler
        if not handler.key_actions.switch_to_app():
            self.logger.warning("Cannot switch to QQ Music for radio playback")
            return PlaybackOutcome.failed("Cannot switch to qq music")
        if not handler.navigate_to_home():
            self.logger.warning("Failed to navigate to QQ Music home for radio playback")
            return PlaybackOutcome.failed("Failed to navigate to home in QQ Music")
        return None

    def _guess_radio(self) -> PlaybackOutcome:
        """`:radio guess` —— 每日猜你喜欢：点开频道卡片，电台自己起播。"""
        failure = self._switch_to_qq_music_home()
        if failure:
            return failure
        handler = self._handler

        title_element = handler.element_finder.wait_for_element_clickable("guess_title")
        topic_element = handler.element_finder.wait_for_element("guess_topic")
        if not title_element or not topic_element:
            return PlaybackOutcome.failed("Failed to locate guess like radio elements")
        room_title = title_element.text or ""
        topic = self._radio_subtitle_topic(topic_element.text)

        title_element.click()
        self.logger.info(f"已进入猜你喜欢电台: {room_title}")

        return PlaybackOutcome.started(
            PlaybackTrack(song=topic or ""),
            title=room_title,
            topic=topic,
            playlist=room_title,
            extra={"playlist": self._radio_queue_text(room_title)},
        )

    def _daily_radio(self) -> PlaybackOutcome:
        """`:radio daily` —— 每日 30 首：点开频道卡片后还要再点「播放全部」。"""
        failure = self._switch_to_qq_music_home()
        if failure:
            return failure
        handler = self._handler

        title_element = handler.element_finder.wait_for_element_clickable("daily_title")
        topic_element = handler.element_finder.wait_for_element("daily_topic")
        if not title_element or not topic_element:
            return PlaybackOutcome.failed("Failed to locate daily radio elements")
        room_title = title_element.text or ""
        # 卡片上的频道标签只当兜底：队列读得到时话题以队列第一行为准 ——
        # 用户在房间里看到的是正在放的那首歌，不是频道名。
        topic = self._radio_subtitle_topic(topic_element.text)

        title_element.click()
        play_all = handler.element_finder.wait_for_element_clickable("play_all")
        if not play_all:
            return PlaybackOutcome.failed("Failed to locate play all button")
        play_all.click()
        self.logger.info(f"已进入每日 30 首电台: {room_title}")

        playlist_text, first_line, error = self._read_radio_queue()
        if error:
            self.logger.warning(
                f"Failed to read daily radio playlist after playback started: {error}"
            )
        elif first_line:
            topic = first_line.split(" - ")[0].strip() or topic

        return PlaybackOutcome.started(
            PlaybackTrack(song=topic or ""),
            title=room_title,
            topic=topic,
            playlist=room_title,
            extra={"playlist": playlist_text or room_title},
        )

    def _collection_radio(self) -> PlaybackOutcome:
        """`:radio collection`（裸 `:radio`）—— 精选：推荐太老就换一首。

        精选频道是一次性推荐的电台，播出来的那首是频道替房间挑的 —— 老歌就该换，
        而不是照播。这是全套命令里唯一一处「反复换推荐直到能播」的编排，因此
        老歌判定必须与别处逐字一致：这里不自己查发行日期，判定交给
        `MusicManager._is_old_song`（见 `_collection_candidate_is_old`）。
        """
        failure = self._switch_to_qq_music_home()
        if failure:
            return failure
        handler = self._handler

        state_key, state_element = handler.element_finder.wait_for_any_element(
            RADIO_COLLECTION_STATE_KEYS
        )
        if state_key == "pause_collection":
            # 正在播「精选」意味着频道不会因为点开卡片而换歌，只能先回首页让它换。
            self.logger.info("正在播放精选，刷新推荐")
            home_nav = handler.element_finder.wait_for_element_clickable("home_nav")
            if home_nav:
                home_nav.click()
            play_button = handler.element_finder.wait_for_element_clickable(
                "play_collection"
            )
        elif state_key == "play_collection":
            play_button = state_element
        else:
            return PlaybackOutcome.failed("Failed to find collection play button")
        if not play_button:
            return PlaybackOutcome.failed("Failed to find collection play button")

        title_element = handler.element_finder.wait_for_element_clickable(
            "collection_title"
        )
        topic_element = handler.element_finder.wait_for_element("collection_topic")
        if not title_element or not topic_element:
            return PlaybackOutcome.failed("Failed to locate collection radio elements")
        station_name = self._read_collection_station_name(title_element)

        budget = self._radio_refresh_budget()
        refresh_count = 0
        while True:
            candidate = self._read_collection_candidate(topic_element)
            if not candidate:
                return PlaybackOutcome.failed("Failed to read collection radio topic")
            if not self._collection_candidate_is_old(candidate):
                break
            if refresh_count >= budget:
                self.logger.warning(
                    f"精选推荐连换 {refresh_count} 次仍是老歌，照播: {candidate}"
                )
                break
            refresh_count += 1
            self.logger.info(
                f"精选推荐是老歌，换一首 ({refresh_count}/{budget}): {candidate}"
            )
            refreshed = self._refresh_collection_radio()
            if isinstance(refreshed, PlaybackOutcome):
                return refreshed
            play_button, topic_element = refreshed

        play_button.click()
        self.logger.info(f"已进入精选电台: {station_name}")

        playlist_text, first_song, error = self._read_radio_queue()
        if error:
            self.logger.warning(
                f"Failed to read collection playlist after playback started: {error}"
            )
            playlist_text = station_name
            first_song = None

        song_name = first_song.split(" - ")[0].strip() if first_song else ""
        return PlaybackOutcome.started(
            PlaybackTrack(song=song_name),
            # 房名取队列第一首歌的歌名（与迁移前同一取值），话题取电台名。
            title=song_name or station_name,
            topic=station_name,
            playlist=station_name,
            extra={"playlist": playlist_text},
        )

    def _read_collection_station_name(self, title_element) -> str:
        """精选卡片的无障碍标题 → 电台上的一句频道名。

        `content-desc` 上挂着一串「频道名 + 「本期甄选」 + 控件说明」，直接拿整串
        当房名会把控件说明也喊出来，因此按控件说明与书名号裁掉尾巴。

        注意读取走的是 **QQ Music handler** 的 `element_finder`：迁移前这里借的是
        Soul handler 的 finder 去问一个 QQ Music 的控件，两者没有任何关系 ——
        换过来之后这条路径才真正属于它操作的 UI。
        """
        raw = self._handler.element_finder.try_get_attribute(
            title_element, "content-desc"
        ) or "Unknown"
        for splitter in ("音频按钮", "「"):
            if splitter in raw:
                raw = raw.split(splitter)[0 if splitter == "音频按钮" else 1]
        if "」" in raw:
            raw = raw.split("」")[0]
        return raw

    def _read_collection_candidate(self, topic_element) -> Optional[str]:
        """读精选推荐的歌名；元素失效时重新找，最多三次。

        频道会自己在首页刷新卡片，topic 控件随时可能变成失效引用；直接读会让一次
        纯 UI 时序抖动变成整条电台的失败。
        """
        for attempt in range(1, RADIO_STALE_RETRIES + 1):
            try:
                return self._radio_subtitle_topic(topic_element.text)
            except StaleElementReferenceException:
                self.logger.warning(
                    "Radio collection topic element stale, refinding topic "
                    f"({attempt}/{RADIO_STALE_RETRIES})"
                )
                topic_element = self._handler.element_finder.wait_for_element(
                    "collection_topic"
                )
                if not topic_element:
                    return None
        return None

    def _refresh_collection_radio(self):
        """换一首精选推荐：回首页 → 重新认播放按钮与推荐歌名。

        Returns:
            `(播放按钮, 推荐歌名元素)`；任何一步认不出来则返回一个 `PlaybackOutcome`
            失败，由调用方直接转交。
        """
        handler = self._handler
        home_nav = handler.element_finder.wait_for_element_clickable("home_nav")
        if not home_nav:
            return PlaybackOutcome.failed(
                "Failed to find home navigation while refreshing radio"
            )
        home_nav.click()

        play_button = handler.element_finder.wait_for_element_clickable(
            "play_collection"
        )
        if not play_button:
            return PlaybackOutcome.failed(
                "Failed to find collection play button after refresh"
            )
        topic_element = handler.element_finder.wait_for_element("collection_topic")
        if not topic_element:
            return PlaybackOutcome.failed(
                "Failed to locate collection radio topic after refresh"
            )
        return play_button, topic_element

    def _radio_refresh_budget(self) -> int:
        """精选推荐最多换几次。配置缺失或非法时退回既有默认 5 次。"""
        manager = self._music_manager()
        config = getattr(manager, "config", None) or {}
        filter_config = config.get("old_song_filter", {}) or {}
        try:
            return int(filter_config.get("radio_max_refreshes", 5))
        except (TypeError, ValueError):
            return 5

    def _collection_candidate_is_old(self, candidate: str) -> bool:
        """精选推荐算不算老歌 —— 判定归 `MusicManager`，这里不再实现一遍。

        迁移前 `RadioCommand` 自带一份发行日期查询 + 截止日期比较，与
        `MusicManager._is_old_song` 逐字重复：两份实现意味着艺人白名单与「用户单点
        的歌不跳过」这两条既定规则只在 `:radio` 上失效。现在这里只调用它，
        全仓库的老歌判定因此只剩一个实现。
        """
        manager = self._music_manager()
        if manager is None:
            return False
        return bool(manager._is_old_song(candidate))

    @staticmethod
    def _radio_subtitle_topic(raw_topic: Optional[str]) -> Optional[str]:
        """电台卡片副标题 → 话题文案。

        **刻意不等于 `PlaylistAdoption.primary_topic()`**：那边按 `" - "` 拆，因为
        队列行「歌名 - 歌手」里的分隔符必须原样保留，裸连字符是 Lo-Fi 之类歌名的
        组成部分；而电台卡片上那行副标题本身就是「题材 - 年代」的写法，分隔符就是
        一个裸的 `-`。两套约定各有道理（`primary_topic` 的 docstring 专门警告过别
        混用），因此这里沿用电台自己的拆法，不为了统一而统一。
        """
        if not raw_topic:
            return None
        parts = [segment.strip() for segment in raw_topic.split("-") if segment.strip()]
        if not parts:
            return raw_topic.strip() or None
        return parts[0]

    def _read_radio_queue(self) -> tuple:
        """读起播后的队列，返回 `(队列文本, 队列第一行, 错误)`。"""
        playlist_text, first_line, error = get_playlist_text_and_first_song(
            self._handler.get_playlist_info()
        )
        return playlist_text, first_line, error

    def _radio_queue_text(self, fallback: str) -> str:
        """队列读不出来时的兜底：读不到队列不是失败，歌已经在放了。

        报错会让用户以为歌没响，因此退回频道名并按 warning 记一笔（与迁移前命令层
        的同一时刻、同一兜底）。
        """
        playlist_text, _, error = self._read_radio_queue()
        if error:
            self.logger.warning(
                f"Failed to read radio playlist after playback started: {error}"
            )
            return fallback
        return playlist_text

    def _sleep_radio(self) -> PlaybackOutcome:
        """`:radio sleep` —— 音乐疗愈：首页标签要横向滑到「疗愈」才看得见。"""
        failure = self._switch_to_qq_music_home()
        if failure:
            return failure
        handler = self._handler

        _, healing_tab, _ = handler.gesture_handler.scroll_container_until_element(
            "home_tab_label",
            "home_tab_strip",
            "left",
            "text",
            RADIO_HEALING_TAB_LABEL,
            max_swipes=RADIO_HEALING_MAX_SWIPES,
        )
        if not healing_tab:
            return PlaybackOutcome.failed(
                f"Failed to scroll home tabs to {RADIO_HEALING_TAB_LABEL} column"
            )
        healing_tab.click()
        self.logger.info("Clicked 疗愈 tab after scrolling home tab strip")

        play_healing = handler.element_finder.wait_for_element_clickable(
            "play_healing"
        )
        if not play_healing:
            return PlaybackOutcome.failed("Failed to find healing play button")
        play_healing.click()

        playlist_text, first_song, error = self._read_radio_queue()
        if error:
            self.logger.warning(
                f"Failed to read healing playlist after playback started: {error}"
            )
            playlist_text = RADIO_HEALING_ROOM_NAME
            first_song = None

        # 疗愈是整站的一条长电台：留在详情页会把首页其它频道的入口挡住，
        # 下一次换台先得退回首页。
        if not handler.navigate_to_home():
            return PlaybackOutcome.failed("Failed to navigate to home")

        return PlaybackOutcome.started(
            PlaybackTrack(song=(first_song or "").split(" - ")[0].strip()),
            title=RADIO_HEALING_ROOM_NAME,
            topic=first_song,
            playlist=RADIO_HEALING_ROOM_NAME,
            extra={"playlist": playlist_text},
        )

    def _radio_radar(self) -> PlaybackOutcome:
        """`:radio radar` —— 雷达电台：点进频道就等于开了播。

        与 `:play ?`（`PlaybackMode.RADAR`）是同一屏 UI，但语义不同：这里是房间主动
        开的一个电台，要连队列一起广播；那里是 QQ Music 的常驻雷达流量。因此本编排
        读队列（队列文本即这次广播的歌单），而 `PlaybackMode.RADAR` 刻意不读 ——
        它读到的是电台的历史列表，不是这次要广播的东西。
        """
        failure = self._switch_to_qq_music_home()
        if failure:
            return failure
        handler = self._handler

        radar_nav = handler.element_finder.try_find_element("radar_nav", log=False)
        if not radar_nav:
            return PlaybackOutcome.failed("Cannot find radar_nav")
        radar_nav.click()
        self.logger.info("Clicked radar navigation button")

        song_element = handler.element_finder.wait_for_element_clickable("radar_song")
        singer_element = handler.element_finder.wait_for_element_clickable("radar_singer")
        if not song_element or not singer_element:
            return PlaybackOutcome.failed(
                "Failed to locate radar song or singer elements"
            )

        return PlaybackOutcome.started(
            PlaybackTrack(
                song=song_element.text or "",
                singer=singer_element.text or "",
            ),
            title=RADIO_RADAR_ROOM_NAME,
            topic=song_element.text,
            playlist=RADIO_RADAR_ROOM_NAME,
            extra={"playlist": self._radio_queue_text(RADIO_RADAR_ROOM_NAME)},
        )

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
        """读点完「播放全部」之后的播放队列，作为给用户的回复正文。"""
        playlist_text, _ = self._read_queue(fallback)
        return playlist_text

    def _read_queue(self, fallback: str) -> tuple:
        """读点完「播放全部」之后的播放队列，回 `(队列文本, 队列首行)`。

        读不到队列不是失败：歌已经在放了，把失败报给用户会让人以为歌没响。因此
        退回 `fallback`，并按 warning 记一笔（与迁移前命令层的同一时刻、同一兜底）。

        Args:
            fallback: 队列读不出来时改用的名字。

        Returns:
            `(队列文本或兜底值, 队列首行)`；读不到队列时首行为 None。
        """
        playlist_text, first_line, error = get_playlist_text_and_first_song(
            self._handler.get_playlist_info()
        )
        if error:
            self.logger.warning(
                f"Failed to read playlist after playback started: {error}"
            )
            return fallback, None
        return playlist_text, first_line

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
    # 歌手播放（#437）
    #
    # 歌手有两条差别很大的 UI 通路：首页上那张「播放歌手: X 的歌曲」的卡点一下
    # 就等于播他全部；页面上没有那张卡时才退回分类页，点开歌手再点「播放全部」。
    # 两条通路的产物相同（一个歌手的歌单），因此骨架只写一遍。
    # ------------------------------------------------------------------

    def _play_singer(self, query: str) -> PlaybackOutcome:
        """`:singer <query>` 的 UI 编排。"""
        try:
            return self._run_singer_flow(query)
        except Exception as exc:
            # 带上原始原因：Appium 的失败原因（会话断开、控件不可交互……）互相之间
            # 完全不同，只报「歌手播放失败」会让线上问题无从区分。
            self.logger.warning(f"播放歌手歌单失败: {query}: {exc}")
            return PlaybackOutcome.failed(f"Failed to play singer: {query}: {exc}")

    def _run_singer_flow(self, query: str) -> PlaybackOutcome:
        from_key = self._handler.query_music(query)
        if not from_key:
            self.logger.warning(f"Failed to query singer {query}")
            return PlaybackOutcome.failed(f"Failed to query singer {query}")

        shortcut = self._singer_shortcut(from_key)
        if shortcut is not None:
            button, singer_name = shortcut
            button.click()
            self.logger.info(f"已通过首页快捷键开始播放歌手: {singer_name}")
        else:
            error, singer_name = self._singer_from_tab(query)
            if error:
                return PlaybackOutcome.failed(error)

        # 先读曲目再读队列：读队列要拉起播放队列面板，面板盖住列表之后
        # `result_item` 就找不到了。
        song, singer = self._read_first_track()
        queue_text, first_line = self._read_queue(fallback=singer_name)

        return PlaybackOutcome.started(
            PlaybackTrack(song=song, singer=singer),
            title=singer_name,
            # 队列首行形如「歌名 - 歌手」，`PlaylistAdoption` 按 " - " 取歌名做话题。
            topic=first_line or singer_name,
            playlist=singer_name,
            extra={"playlist": queue_text},
        )

    def _singer_shortcut(self, from_key: Optional[str]):
        """首页上的歌手快捷键。返回 None 表示这条捷径走不通，该走分类页。

        只在 `query_music` 从首页进搜索时才试：那张卡只在首页上，从搜索框进去的
        搜索结果页根本没有它，硬找只会白等一次超时。

        Returns:
            `(可点的快捷键元素, 歌手名)`；页面上没有快捷键时为 None。
        """
        if from_key != "home_nav":
            return None

        finder = self._handler.element_finder
        key, _ = finder.wait_for_any_element(SINGER_SHORTCUT_KEYS, timeout=5)
        if not key or key == "not_found":
            return None

        shortcut = finder.try_find_element("play_singer_1")
        if shortcut is not None:
            # 新版卡片把歌手名写在 content-desc 里，点之前先读出来当房名。
            content_desc = finder.try_get_attribute(shortcut, "content-desc")
            return shortcut, _singer_name_from_content_desc(content_desc)

        # 老版本只有一张没有文案的按钮，歌手名在旁边另一个控件上。
        legacy = finder.try_find_element("play_singer")
        if legacy is not None:
            name_element = finder.try_find_element("singer_name")
            name = (name_element.text or "").strip() if name_element else ""
            return legacy, name or UNKNOWN_SINGER_NAME
        return None

    def _singer_from_tab(self, query: str) -> tuple:
        """分类页那条路：切歌手 tab → 点歌手 → 点播放全部。

        Returns:
            `(错误说明, 歌手名)`；成功时错误为 None。
        """
        if not self._select_category_tab("singer"):
            self.logger.warning(f"Failed to select singer tab with query {query}")
            return f"not found singer with query {query}", UNKNOWN_SINGER_NAME

        key, element = self._handler.element_finder.wait_for_any_element(
            SINGER_RESULT_KEYS
        )
        if not key or key == "not_found" or not element:
            self.logger.warning(f"not found singer with query {query}")
            return f"not found singer with query {query}", UNKNOWN_SINGER_NAME

        element.click()
        singer_name = (element.text or "").strip() or UNKNOWN_SINGER_NAME
        self.logger.info(f"已点开歌手: {singer_name}")

        # 与收藏/歌单共用同一次「播放全部」点击：认不出按钮就是认不出，三条
        # 通路对这件事没有各自的看法。
        play_error = self._click_play_all()
        if play_error:
            return play_error, singer_name
        return None, singer_name

    # ------------------------------------------------------------------
    # 专辑播放（#437）
    # ------------------------------------------------------------------

    def _play_album(self, query: str) -> PlaybackOutcome:
        """`:album <query>` 的 UI 编排。"""
        try:
            return self._run_album_flow(query)
        except Exception as exc:
            self.logger.warning(f"播放专辑失败: {query}: {exc}")
            return PlaybackOutcome.failed(f"Failed to play album: {query}: {exc}")

    def _run_album_flow(self, query: str) -> PlaybackOutcome:
        handler = self._handler

        query = self._album_query(query)
        if not query:
            return PlaybackOutcome.failed("Failed to get playback info")

        if not handler.query_music(query):
            self.logger.warning(f"Failed to query album with query {query}")
            return PlaybackOutcome.failed("Failed to query album")

        if not self._select_category_tab("album"):
            self.logger.warning(f"Failed to select album tab with query {query}")
            return PlaybackOutcome.failed("Failed to select album tab")

        key, _ = handler.element_finder.wait_for_any_element(ALBUM_RESULT_KEYS)
        if not key or key == "not_found":
            self.logger.warning(f"Not found album result with query {query}")
            return PlaybackOutcome.failed(
                f"Failed to find album result with query {query}"
            )

        card = self._album_card()
        if card is None:
            return PlaybackOutcome.failed("Failed to find album result")
        album_name, album_singer = card
        # 房名/话题/歌单名都用文案，不用控件本身 —— 控件会被页面重排带走。
        album_title = (album_name.text or "").strip()
        album_artist = (album_singer.text or "").strip()

        album_name.click()
        self.logger.info(f"已点开专辑: {album_title}")

        play_error = self._click_play_all()
        if play_error:
            return PlaybackOutcome.failed(play_error)

        song, singer = self._read_first_track()
        # 读队列之前先取曲目：队列面板会盖住专辑的歌曲列表。
        room_playlist = f"{album_artist} - {album_title}"
        queue_text, _ = self._read_queue(fallback=room_playlist)

        # 专辑详情页是盖在搜索结果上的：不按返回键把它收掉，后面引擎去 Soul 改
        # 标题/话题时弹窗会压在它下面。
        handler.key_actions.press_back()

        return PlaybackOutcome.started(
            PlaybackTrack(song=song, singer=singer, album=album_title),
            title=album_artist,
            topic=album_title,
            playlist=room_playlist,
            extra={"playlist": queue_text},
        )

    def _album_query(self, query: str) -> str:
        """`:album` 不带参数 = 播「现在这首所在的专辑」。

        查询词由当前播放的「歌名 歌手 专辑」拼出来。三样都要带上：QQ Music 的专辑
        检索认得专辑名，可同名专辑不少，只给专辑名容易选错碟。读不到当前播放就
        返回空串，让调用方如实报失败，而不是拿一个空查询词去搜。
        """
        if query:
            return query
        try:
            from ushareiplay.managers.music_manager import MusicManager

            info = MusicManager.instance().get_playback_info()
        except Exception as exc:
            self.logger.warning(f"读取当前播放信息失败: {exc}")
            return ""
        if not info:
            self.logger.warning("没有正在播放的歌曲，无法推断要播哪张专辑")
            return ""
        return " ".join(
            str(info.get(field) or "").strip()
            for field in ("song", "singer", "album")
        ).strip()

    def _album_card(self):
        """专辑结果的头两行：`(专辑名控件, 专辑歌手控件)`。

        `album_result` 一次返回整页的 TextView，**至少两行才算一张排版完的卡片**
        （第一行专辑名、第二行歌手）。少于两行说明卡片还没排好：此时点下去点开的
        可能不是那张碟，而房名也会缺歌手。宁可如实报失败，也不拿半张卡片拼房间。

        Returns:
            `(专辑名控件, 歌手控件)`；行数不足时为 None。
        """
        rows = self._handler.element_finder.find_elements("album_result")
        if len(rows) < 2:
            self.logger.warning(f"专辑卡只有 {len(rows)} 行，判定为未排版完")
            return None
        return rows[0], rows[1]

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

    def _music_manager(self):
        """取 `MusicManager` 单例；取不到时如实返回 None。

        与 `_select_category_tab` 同样在函数体内 import：`music_manager` 顶层会
        import 本模块，静态 import 会形成 `driver → music_manager → driver` 的
        循环引用（见本模块的 docstring）。
        """
        try:
            from ushareiplay.managers.music_manager import MusicManager

            return MusicManager.instance()
        except Exception as exc:
            self.logger.warning(f"MusicManager 不可用: {exc}")
            return None

    def _quality_check(self, playing_info: dict) -> None:
        """把解析出的曲目交给老歌过滤；失败不应阻断播放本身。"""
        manager = self._music_manager()
        if manager is None:
            return
        try:
            manager.handle_song_quality_check(playing_info)
        except Exception as exc:
            self.logger.warning(f"歌曲质量检查失败: {exc}")

