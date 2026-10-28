"""`:singer` / `:album` 的 UI 编排（#437）—— `QQMusicUIDriver.start_playback` 的两个模式。

这两条编排的共同点是「结果卡片上写着房间该叫什么，只有 UI 读得到」：歌手名来自
首页快捷键的 `content-desc` 或歌手分类的结果卡片，专辑名/专辑歌手来自专辑卡片的头两行。
命令层拿不到这些文本，因此引擎采纳房名与话题只能靠驱动回填。

替身只实现这两条编排真正触达的方法 —— 驱动多走一步（例如忘了点「播放全部」就
读队列），就会以 AttributeError 暴露出来。分类 tab 的选择由 `playlist_tab` 风格的
fixture 脚本化：驱动只看到 True/False，记录与注入都在 fixture 里。
"""

from types import SimpleNamespace

import pytest

from ushareiplay.managers.playback.models import (
    PlaybackMode,
    PlaybackRequest,
)
from ushareiplay.managers.playback.qq_music_ui_driver import (
    ALBUM_RESULT_KEYS,
    PLAY_ALL_KEYS,
    SINGER_RESULT_KEYS,
    SINGER_SHORTCUT_KEYS,
    QQMusicUIDriver,
)


def _singer_request(query, requester="小明"):
    """构造歌手模式的请求。

    直接构造而不是调 `PlaybackRequest.singer(...)`：仓库里刻意不提供与字段同名的
    构造器（`playlist` 已经是字段），歌手/专辑同样只用「模式 + 查询词 + 请求者」三样。
    """
    return PlaybackRequest(mode=PlaybackMode.SINGER, query=query, requester=requester)


def _album_request(query, requester="小明"):
    return PlaybackRequest(mode=PlaybackMode.ALBUM, query=query, requester=requester)


class _Element:
    """可点击元素的最小替身。"""

    def __init__(self, text="", attrs=None):
        self.text = text
        self.clicks = 0
        self.attrs = dict(attrs or {})

    def click(self):
        self.clicks += 1

    def get_attribute(self, name):
        return self.attrs.get(name)


class _Row:
    """详情页里的一行：第一列歌名、第二列歌手。"""

    def __init__(self, text):
        self.text = text
        self.cells = _Element(text)

    def find_element(self, by, value):
        return self.cells


class _TrackItem:
    """`result_item` 容器：按 LinearLayout 分列，第一列歌名、第二列歌手。"""

    def __init__(self, rows):
        self._rows = [_Row(text) for text in rows]

    def find_elements(self, by, value):
        return self._rows


class _SingerAlbumHandler:
    """歌手/专辑播放用的 handler 表面。

    旋钮对应这两条编排上每个可能失败的关节：`from_key`（`query_music` 从哪进搜索）、
    `shortcut`（首页那张「播放歌手: X 的歌曲」卡）、`singer_result_key` / 
    `album_result_key`（分类页认出的是结果还是「没有找到」）、`album_rows`（专辑卡头
    两行：专辑名与歌手）、`play_all`（认不认得出「播放全部」）、`playlist_info`
    （点完之后读回来的队列）。

    替身只实现被驱动的编排真正触达的方法 —— 驱动多走一步（例如忘了点播放全部就
    读队列），这里就会以 AttributeError 暴露出来。
    """

    def __init__(
        self,
        *,
        from_key="home_nav",
        shortcut_desc="播放歌手: 张天赋的歌曲",
        shortcut=True,
        legacy_shortcut_text=None,
        shortcut_page_key="music_tabs",
        singer_result_key="singer_result",
        singer_result_text="张天赋",
        album_result_key="album_result",
        album_rows=("范特西", "周杰伦"),
        play_all=True,
        first_track=("简单爱", "周杰伦"),
        playlist_info=None,
        playback_info=None,
    ):
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        self.from_key = from_key
        self.shortcut_desc = shortcut_desc
        self.shortcut = shortcut
        self.legacy_shortcut_text = legacy_shortcut_text
        self.shortcut_page_key = shortcut_page_key
        self.singer_result_key = singer_result_key
        self.singer_result_text = singer_result_text
        self.album_result_key = album_result_key
        self.album_rows = tuple(album_rows)
        self.play_all = play_all
        self.track_item = None if first_track is None else _TrackItem(list(first_track))
        self.playback_info = playback_info
        self.playlist_info = (
            {"playlist": "简单爱 - 周杰伦\n爱在西元前 - 周杰伦"}
            if playlist_info is None
            else playlist_info
        )

        self.queries = []
        self.pressed_back = 0
        self.queue_reads = 0

        self.shortcut_button = (
            _Element(attrs={"content-desc": shortcut_desc}) if shortcut else None
        )
        self.legacy_button = (
            _Element() if shortcut is False and legacy_shortcut_text else None
        )
        self.legacy_name = (
            _Element(legacy_shortcut_text) if legacy_shortcut_text else None
        )
        self.singer_result = _Element(singer_result_text)
        self.album_card = _Element()
        self.album_card.rows = [_Element(text) for text in self.album_rows]
        self.play_button = _Element()

        self._element_finder = SimpleNamespace(
            wait_for_any_element=self._wait_any,
            try_find_element=self._try_find,
            find_elements=self._find_elements,
            wait_for_element_clickable=self._wait_clickable,
            try_get_attribute=self._try_attribute,
        )

    @property
    def element_finder(self):
        return self._element_finder

    @property
    def key_actions(self):
        actions = self.__dict__.setdefault(
            "_key_actions", SimpleNamespace(press_back=self._press_back)
        )
        return actions

    def _press_back(self):
        self.pressed_back += 1

    def query_music(self, query):
        self.queries.append(query)
        return self.from_key

    def _wait_any(self, keys, timeout=None):
        keys = list(keys)
        if keys == SINGER_SHORTCUT_KEYS:
            return self.shortcut_page_key, _Element()
        if keys == SINGER_RESULT_KEYS:
            return self.singer_result_key, self.singer_result
        if keys == ALBUM_RESULT_KEYS:
            return self.album_result_key, self.album_card
        if keys == PLAY_ALL_KEYS:
            return "play_all", (self.play_button if self.play_all else None)
        raise AssertionError(f"unexpected keys: {keys}")

    def _try_find(self, key, **kwargs):
        if key == "play_singer_1":
            return self.shortcut_button
        if key == "play_singer":
            return self.legacy_button
        if key == "singer_name":
            return self.legacy_name
        if key == "result_item":
            return self.track_item
        raise AssertionError(f"unexpected key: {key}")

    def _find_elements(self, key):
        if key != "album_result":
            raise AssertionError(f"unexpected key: {key}")
        return list(self.album_card.rows)

    def _wait_clickable(self, key, timeout=None):
        if key != "play_all":
            raise AssertionError(f"unexpected key: {key}")
        return self.play_button if self.play_all else None

    @staticmethod
    def _try_attribute(element, attribute):
        return element.get_attribute(attribute)

    def get_playlist_info(self):
        self.queue_reads += 1
        return self.playlist_info


@pytest.fixture
def category_tab(initialized_test_singletons):
    """脚本化的分类 tab 选择：驱动只看到 True/False，这里负责记录与注入。"""
    from ushareiplay.managers.music_manager import MusicManager

    class _TabSelection:
        def __init__(self):
            self.calls = []
            self.available = True

        def __call__(self, name, **kwargs):
            self.calls.append(name)
            return self.available

    tabs = _TabSelection()
    MusicManager.initialize().select_tab = tabs
    return tabs


@pytest.fixture
def current_playback(initialized_test_singletons):
    """`:album` 不带参数时兜底读的「现在在放什么」。"""
    from ushareiplay.managers.music_manager import MusicManager

    class _PlaybackInfo:
        def __init__(self):
            self.calls = 0
            self.info = {"song": "简单爱", "singer": "周杰伦", "album": "范特西"}

        def __call__(self):
            self.calls += 1
            return self.info

    probe = _PlaybackInfo()
    # 分类 tab 的 fixture 可能已经初始化过同一个单例，这里不能再 initialize。
    manager = (
        MusicManager.instance()
        if MusicManager.is_initialized()
        else MusicManager.initialize()
    )
    manager.get_playback_info = probe
    return probe


# ---------------------------------------------------------------------------
# 歌手：首页快捷键
# ---------------------------------------------------------------------------


def test_driver_prefers_the_home_singer_shortcut_over_the_tab(
    initialized_test_singletons, category_tab
):
    """首页上那张「播放歌手: X 的歌曲」就是一次完整播放：点它等于播他全部。

    走这条捷径时一个分类 tab 都不该切、也不该再找「播放全部」—— 那是两条不同
    编排的兜底关系，反过来会让房间响两次播放。
    """
    handler = _SingerAlbumHandler(shortcut_desc="播放歌手: 张天赋的歌曲")

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert outcome.ok is True
    assert handler.shortcut_button.clicks == 1
    assert category_tab.calls == []
    assert handler.play_button.clicks == 0


def test_driver_reads_the_singer_name_out_of_the_shortcut_content_desc(
    initialized_test_singletons, category_tab
):
    """`content-desc` 形如「播放歌手: 张天赋的歌曲」，房名取中间的歌手名。"""
    handler = _SingerAlbumHandler(shortcut_desc="播放歌手: 张天赋的歌曲")

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert (outcome.title, outcome.topic, outcome.playlist) == ("张天赋", "简单爱 - 周杰伦", "张天赋")


def test_driver_falls_back_to_the_legacy_play_singer_button(
    initialized_test_singletons, category_tab
):
    """老版本没有带文案的那张卡，只有 `play_singer` + 相邻的 `singer_name`。"""
    handler = _SingerAlbumHandler(shortcut=False, legacy_shortcut_text="陈奕迅")

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("陈奕迅"))

    assert outcome.ok is True
    assert outcome.title == "陈奕迅"
    assert category_tab.calls == []


def test_driver_falls_back_to_the_singer_tab_when_no_shortcut_exists(
    initialized_test_singletons, category_tab
):
    """首页没有快捷键时退回分类页：切歌手 tab → 点结果 → 点播放全部。"""
    handler = _SingerAlbumHandler(shortcut=False)

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert outcome.ok is True
    assert category_tab.calls == ["singer"]
    assert handler.singer_result.clicks == 1
    assert handler.play_button.clicks == 1
    assert outcome.title == "张天赋", "房名取歌手卡片上的名字"


def test_driver_falls_back_to_the_singer_tab_when_home_shows_nothing_found(
    initialized_test_singletons, category_tab
):
    """首页直接说「没有找到」时不该硬点快捷键，直接走分类页那条路。"""
    handler = _SingerAlbumHandler(shortcut_page_key="not_found")

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("查无此人"))

    assert outcome.ok is True
    assert handler.shortcut_button.clicks == 0
    assert category_tab.calls == ["singer"]


def test_driver_reports_a_singer_search_that_never_ran(
    initialized_test_singletons, category_tab
):
    """`query_music` 返回 None（搜索框都没进去）时连歌手分类都不该切。"""
    handler = _SingerAlbumHandler(from_key=None)

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert outcome.ok is False
    assert category_tab.calls == []


def test_driver_reports_a_missing_singer_result_instead_of_playing(
    initialized_test_singletons, category_tab
):
    """分类页说「没有找到」：点开了分类却一个歌手都没放，如实报失败。"""
    handler = _SingerAlbumHandler(shortcut=False, singer_result_key="not_found")

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("查无此人"))

    assert outcome.ok is False
    assert handler.play_button.clicks == 0


def test_driver_reports_a_missing_singer_play_all_button(
    initialized_test_singletons, category_tab
):
    handler = _SingerAlbumHandler(shortcut=False, play_all=False)

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert outcome.ok is False
    assert handler.queue_reads == 0


def test_driver_carries_the_queue_text_the_singer_reply_renders(
    initialized_test_singletons, category_tab
):
    """`:singer` 的回复模板是纯 `{playlist}`，它渲染的必须是播放队列本身。"""
    handler = _SingerAlbumHandler(
        playlist_info={"playlist": "简单爱 - 周杰伦\n爱在西元前 - 周杰伦"}
    )

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert outcome.extra["playlist"] == "简单爱 - 周杰伦\n爱在西元前 - 周杰伦"


def test_driver_falls_back_to_the_singer_name_when_the_queue_cannot_be_read(
    initialized_test_singletons, category_tab
):
    """读不到队列是正常结局：歌已经在放，回复退回歌手名，而不是整条失败。"""
    handler = _SingerAlbumHandler(playlist_info={"error": "No songs found in playlist"})

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert outcome.ok is True
    assert outcome.extra["playlist"] == "张天赋"


def test_driver_reports_a_singer_flow_exception_instead_of_raising(
    initialized_test_singletons, category_tab
):
    handler = _SingerAlbumHandler()

    def _boom(_keys, **_kwargs):
        raise RuntimeError("session terminated")

    handler._element_finder.wait_for_any_element = _boom

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert outcome.ok is False
    assert "session terminated" in outcome.error


def test_driver_reports_the_missing_singer_tab(initialized_test_singletons, category_tab):
    category_tab.available = False
    handler = _SingerAlbumHandler(shortcut=False)

    outcome = QQMusicUIDriver(handler).start_playback(_singer_request("张天赋"))

    assert outcome.ok is False
    assert handler.singer_result.clicks == 0


# ---------------------------------------------------------------------------
# 专辑
# ---------------------------------------------------------------------------


def test_driver_walks_the_whole_album_flow_and_reports_what_it_saw(
    initialized_test_singletons, category_tab
):
    """搜专辑 → 切专辑分类 → 点专辑卡 → 点播放全部 → 读队列 → 按返回，一步都不能少。"""
    handler = _SingerAlbumHandler()

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("范特西"))

    assert outcome.ok is True
    assert handler.queries == ["范特西"]
    assert category_tab.calls == ["album"]
    assert handler.album_card.rows[0].clicks == 1
    assert handler.play_button.clicks == 1
    assert handler.queue_reads == 1
    assert handler.pressed_back == 1


def test_driver_splits_the_album_card_into_topic_and_room_title(
    initialized_test_singletons, category_tab
):
    """专辑卡头两行依次是专辑名与歌手：话题取专辑名，房名取歌手。

    与歌手相反是有原因的：房间里播的是这一整张专辑，话题说「哪张碟」比说歌名有用。
    """
    handler = _SingerAlbumHandler(album_rows=("范特西", "周杰伦"))

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("范特西"))

    assert outcome.topic == "范特西"
    assert outcome.title == "周杰伦"
    assert outcome.playlist == "周杰伦 - 范特西"


def test_driver_keeps_the_first_track_of_the_album_in_the_outcome(
    initialized_test_singletons, category_tab
):
    handler = _SingerAlbumHandler(first_track=("简单爱", "周杰伦"))

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("范特西"))

    assert (outcome.track.song, outcome.track.singer) == ("简单爱", "周杰伦")


def test_driver_resolves_an_empty_album_query_from_what_is_playing_now(
    initialized_test_singletons, category_tab, current_playback
):
    """`:album` 不带参数 = 「播现在这首所在的专辑」，查询词由当前播放拼出来。"""
    handler = _SingerAlbumHandler()

    QQMusicUIDriver(handler).start_playback(_album_request(""))

    assert current_playback.calls == 1
    assert handler.queries == ["简单爱 周杰伦 范特西"]


def test_driver_reports_an_empty_album_query_with_nothing_playing(
    initialized_test_singletons, category_tab, current_playback
):
    """连「现在在放什么」都读不到时如实报失败，别拿一个空查询词去搜。"""
    current_playback.info = None
    handler = _SingerAlbumHandler()

    outcome = QQMusicUIDriver(handler).start_playback(_album_request(""))

    assert outcome.ok is False
    assert handler.queries == []


def test_driver_refuses_an_album_card_that_lost_its_singer_row(
    initialized_test_singletons, category_tab
):
    """专辑卡要求至少两行（专辑名 + 歌手）。只有一行说明卡片没排版完。

    宁可如实报失败，也不要拿半张卡片拼出一个只有专辑名、没有歌手的房间标题。
    """
    handler = _SingerAlbumHandler(album_rows=("范特西",))

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("范特西"))

    assert outcome.ok is False
    assert handler.album_card.rows[0].clicks == 0
    assert handler.play_button.clicks == 0


def test_driver_reports_a_missing_album_result_instead_of_playing(
    initialized_test_singletons, category_tab
):
    handler = _SingerAlbumHandler(album_result_key="not_found")

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("查无此碟"))

    assert outcome.ok is False
    assert handler.play_button.clicks == 0


def test_driver_reports_an_album_search_that_never_ran(
    initialized_test_singletons, category_tab
):
    handler = _SingerAlbumHandler(from_key=None)

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("范特西"))

    assert outcome.ok is False
    assert category_tab.calls == []


def test_driver_reports_a_missing_album_play_all_button(
    initialized_test_singletons, category_tab
):
    """认出了专辑却没有「播放全部」：点开了详情页但一首都没放，如实报失败。"""
    handler = _SingerAlbumHandler(play_all=False)

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("范特西"))

    assert outcome.ok is False
    assert handler.queue_reads == 0
    assert handler.pressed_back == 0


def test_driver_falls_back_to_singer_and_album_when_the_queue_cannot_be_read(
    initialized_test_singletons, category_tab
):
    """队列读不出来时回复退回「歌手 - 专辑」，与迁移前同一时刻、同一兜底。"""
    handler = _SingerAlbumHandler(playlist_info={"error": "No songs found in playlist"})

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("范特西"))

    assert outcome.ok is True
    assert outcome.extra["playlist"] == "周杰伦 - 范特西"


def test_driver_reports_the_missing_album_tab(initialized_test_singletons, category_tab):
    category_tab.available = False
    handler = _SingerAlbumHandler()

    outcome = QQMusicUIDriver(handler).start_playback(_album_request("范特西"))

    assert outcome.ok is False
    assert handler.album_card.rows[0].clicks == 0


# ---------------------------------------------------------------------------
# 请求契约：模式、查询词、请求者
# ---------------------------------------------------------------------------


def test_singer_and_album_requests_do_not_borrow_the_radio_channel_field(initialized_test_singletons):
    """`channel` 是电台频道的位置，歌手/专辑只用「查询词」一种输入。"""
    for mode in (PlaybackMode.SINGER, PlaybackMode.ALBUM):
        request = PlaybackRequest(mode=mode, query="张天赋", requester="小明")
        assert request.channel is None
        assert request.variant is None
