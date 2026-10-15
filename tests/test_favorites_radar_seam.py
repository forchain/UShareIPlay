"""#425：收藏三种形态与雷达流量的离线测试。

测试面是 `QQMusicUIDriver.start_playback(request)` 这一个端口方法：请求带上模式与
（收藏的）形态，断言返回的 `PlaybackOutcome` —— 播起来了没有、观察到哪首歌、房间标题
与话题该是什么、`{playlist}` 里该放歌单全文还是歌单名。

QQMusicHandler 由本模块的假替身提供，只暴露驱动真正调用的那几个 UI 方法（切前台、
进收藏页、读首行、点播放全部、收藏内搜索、读歌单、回首页、雷达页）。因此断言考的是
「驱动怎么编排收藏的三个形态」，而不是「Appium 点了哪个坐标」。

无 Appium、无真机、无 `dumpsys`。
"""

from types import SimpleNamespace

import pytest
from selenium.common.exceptions import NoSuchElementException

from ushareiplay.managers.playback.models import (
    PlaybackMode,
    PlaybackRequest,
    PlaybackVariant,
)
from ushareiplay.managers.playback.qq_music_ui_driver import QQMusicUIDriver

QUEUE_TEXT = "喜帖街 - 谢安琪\n富士山下 - 陈奕迅"


class _Element:
    """可点元素的最小替身；`text_views` 供 `result_item` 那一类容器使用。"""

    def __init__(self, text="", text_views=(), location=None, size=None):
        self.text = text
        self.text_views = list(text_views)
        self.clicks = 0
        self.location = location or {"x": 100, "y": 200}
        self.size = size or {"width": 120, "height": 48}

    def click(self):
        self.clicks += 1

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def find_elements(self, _by, _value):
        return list(self.text_views)


class _KeyActions:
    def __init__(self, handler):
        self._handler = handler
        self.switches = 0
        self.clipboard = None
        self.pastes = 0

    def switch_to_app(self):
        self.switches += 1
        return self._handler.switch_ok

    def set_clipboard_text(self, text):
        self.clipboard = text

    def paste_text(self):
        self.pastes += 1
        return True

    def press_back(self):
        return None


class _GestureHandler:
    def __init__(self):
        self.swipes = []

    def swipe(self, x1, y1, x2, y2, duration_ms=0):
        self.swipes.append((x1, y1, x2, y2, duration_ms))


class _ElementFinder:
    """按 key 返回元素；`missing` 里的 key 模拟「页面上压根没有这个控件」。"""

    def __init__(self, elements, missing=()):
        self.elements = elements
        self.missing = set(missing)
        self.requested = []

    def _find(self, key):
        self.requested.append(key)
        return None if key in self.missing else self.elements.get(key)

    def try_find_element(self, key, log=False):
        return self._find(key)

    def wait_for_element_clickable(self, key, timeout=None):
        return self._find(key)

    def wait_for_element(self, key, timeout=None):
        return self._find(key)


class _AppiumDriver:
    """收藏筛选页用的原始 XPath 定位（筛选项与「确定（n首）」是动态文案，
    `config.yaml` 里没有对应 key，只能走 raw XPath）。"""

    def __init__(self, option, confirm):
        self.option = option
        self.confirm = confirm
        self.locators = []

    def find_element(self, _by, xpath):
        self.locators.append(xpath)
        if "确定（" in xpath:
            return self.confirm
        return self.option


class _QQMusicHandlerFake:
    """收藏与雷达编排实际使用的 QQMusicHandler 表面。

    只实现被驱动的这几条路径；任何额外调用都会以 AttributeError 暴露出来，避免
    测试在驱动悄悄多做事时仍然通过。
    """

    def __init__(
        self,
        *,
        queue=None,
        queue_error=None,
        open_error=None,
        switch_ok=True,
        missing=(),
        filter_option=None,
        filter_confirm=None,
        radar_song_text="雷达电台",
        radar_singer_text="O Radio",
    ):
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
            debug=lambda *_a, **_k: None,
        )
        self.queue = queue
        self.queue_error = queue_error
        self.open_error = open_error
        self.switch_ok = switch_ok
        self.home_visits = 0
        self.opened_favourites = 0

        self.result_item = _Element(
            text_views=[
                _Element(text="0"),
                _Element(text="喜帖街"),
                _Element(text="谢安琪"),
            ]
        )
        self.radar_nav = _Element(text="雷达")
        self.radar_song = _Element(text=radar_song_text)
        self.radar_singer = _Element(text=radar_singer_text)
        self.elements = {
            "result_item": self.result_item,
            "play_all": _Element(text="全部播放"),
            "filter_favourite": _Element(text="筛选"),
            "search_box": _Element(text="搜索我收藏的歌曲"),
            "favourite_search": _Element(text="搜索我收藏的歌曲"),
            "play_favourite_search": _Element(text="全部播放"),
            "radar_nav": self.radar_nav,
            "radar_song": self.radar_song,
            "radar_singer": self.radar_singer,
        }
        self._element_finder = _ElementFinder(self.elements, missing=missing)
        self.key_actions = _KeyActions(self)
        self.gesture_handler = _GestureHandler()
        self.driver = _AppiumDriver(filter_option, filter_confirm)

    @property
    def element_finder(self):
        return self._element_finder

    def open_favorites_entry(self, timeout=10):
        self.opened_favourites += 1
        return self.open_error

    def get_playlist_info(self):
        if self.queue_error:
            return {"error": self.queue_error}
        return {"playlist": self.queue}

    def navigate_to_home(self):
        self.home_visits += 1
        return True


def _driver(handler):
    return QQMusicUIDriver(handler)


# ---------------------------------------------------------------------------
# Slice 1: 请求形状 —— 三种收藏形态怎么在请求里表达
# ---------------------------------------------------------------------------


def test_favourites_request_without_a_keyword_asks_for_every_favourite():
    request = PlaybackRequest.favorites(requester="小明")

    assert request.mode is PlaybackMode.FAVORITES
    assert request.variant is PlaybackVariant.ALL
    assert request.query is None
    # 队列内容调用方无从预知，就绪校验只能看播放状态本身。
    assert request.expected_song is None


def test_favourites_request_carries_the_filter_keyword_as_its_query():
    request = PlaybackRequest.favorites("粤语", variant=PlaybackVariant.FILTER)

    assert request.variant is PlaybackVariant.FILTER
    assert request.query == "粤语"


def test_favourites_request_carries_the_search_keyword_as_its_query():
    request = PlaybackRequest.favorites("陈奕迅", variant=PlaybackVariant.SEARCH)

    assert request.variant is PlaybackVariant.SEARCH
    assert request.query == "陈奕迅"


def test_radar_request_has_no_query_and_no_variant():
    request = PlaybackRequest.radar(requester="小红")

    assert request.mode is PlaybackMode.RADAR
    assert request.query is None
    assert request.variant is None
    assert request.requester == "小红"


# ---------------------------------------------------------------------------
# Slice 2: 收藏 —— 播放全部
# ---------------------------------------------------------------------------


def test_favourites_all_plays_the_queue_and_adopts_the_station_as_the_room_name(
    initialized_test_singletons,
):
    handler = _QQMusicHandlerFake(queue=QUEUE_TEXT)

    outcome = _driver(handler).start_playback(
        PlaybackRequest.favorites(requester="小明")
    )

    assert outcome.ok is True
    assert handler.key_actions.switches == 1
    assert handler.opened_favourites == 1
    assert handler.elements["play_all"].clicks == 1
    # 房间认的是站名；房间里广播出去的才是歌单全文。
    assert outcome.title == "O Station"
    assert outcome.playlist == "O Station"
    assert outcome.extra["playlist"] == QUEUE_TEXT
    # 话题来自队列第一行，播完先回首页再让引擎去同步房间。
    assert outcome.topic == "喜帖街 - 谢安琪"
    assert handler.home_visits == 1


def test_favourites_all_reports_the_first_row_as_the_track(initialized_test_singletons):
    handler = _QQMusicHandlerFake(queue=QUEUE_TEXT)

    outcome = _driver(handler).start_playback(PlaybackRequest.favorites(requester="小明"))

    assert (outcome.track.song, outcome.track.singer) == ("喜帖街", "谢安琪")


def test_favourites_all_falls_back_to_the_first_row_text_when_the_queue_is_unreadable(
    initialized_test_singletons,
):
    """歌单读不出来时播放已经在进行中 —— 报错不该把已经响起的歌收回去。"""
    handler = _QQMusicHandlerFake(queue=None, queue_error="Cannot read playlist")

    outcome = _driver(handler).start_playback(PlaybackRequest.favorites(requester="小明"))

    assert outcome.ok is True
    assert outcome.topic == "喜帖街"
    assert outcome.extra["playlist"] == "O Station"


def test_favourites_all_reports_a_failure_when_the_favourites_page_will_not_open(
    initialized_test_singletons,
):
    handler = _QQMusicHandlerFake(open_error={"error": "Cannot find fav_entry"})

    outcome = _driver(handler).start_playback(PlaybackRequest.favorites(requester="小明"))

    assert outcome.ok is False
    assert outcome.error == "Cannot find fav_entry"
    assert handler.elements["play_all"].clicks == 0


def test_favourites_all_reports_a_failure_when_there_is_no_play_all_button(
    initialized_test_singletons,
):
    handler = _QQMusicHandlerFake(missing={"play_all"})

    outcome = _driver(handler).start_playback(PlaybackRequest.favorites(requester="小明"))

    assert outcome.ok is False
    assert handler.opened_favourites == 1


# ---------------------------------------------------------------------------
# Slice 3: 收藏 —— 按语种/流派筛选
# ---------------------------------------------------------------------------


def test_favourites_filter_narrows_the_list_then_renames_the_room_by_the_keyword(
    initialized_test_singletons,
):
    option = _Element(text="粤语")
    confirm = _Element(text="确定（12首）")
    handler = _QQMusicHandlerFake(queue=QUEUE_TEXT, filter_option=option, filter_confirm=confirm)

    outcome = _driver(handler).start_playback(
        PlaybackRequest.favorites("粤语", variant=PlaybackVariant.FILTER)
    )

    assert outcome.ok is True
    assert handler.elements["filter_favourite"].clicks == 1
    assert option.clicks == 1
    assert confirm.clicks == 1
    assert handler.elements["play_all"].clicks == 1
    # 粤语在房间里叫「粤音」，站名不再通用。
    assert outcome.title == "粤音"
    assert outcome.playlist == "粤音"
    assert outcome.extra["playlist"] == QUEUE_TEXT
    assert outcome.extra["count"] == 12


def test_favourites_filter_keeps_the_keyword_verbatim_when_it_has_no_short_room_name(
    initialized_test_singletons,
):
    handler = _QQMusicHandlerFake(
        queue=QUEUE_TEXT,
        filter_option=_Element(text="流行"),
        filter_confirm=_Element(text="确定（3首）"),
    )

    outcome = _driver(handler).start_playback(
        PlaybackRequest.favorites("流行", variant=PlaybackVariant.FILTER)
    )

    assert outcome.title == "流行"


def test_favourites_filter_reports_a_failure_when_the_keyword_matches_no_option(
    initialized_test_singletons,
):
    handler = _QQMusicHandlerFake(
        queue=QUEUE_TEXT,
        filter_option=_Element(text=""),
        filter_confirm=_Element(text="确定（0首）"),
    )

    def _no_such_element(*_args):
        raise NoSuchElementException("no such option")

    handler.driver.find_element = _no_such_element

    outcome = _driver(handler).start_playback(
        PlaybackRequest.favorites("不存在", variant=PlaybackVariant.FILTER)
    )

    assert outcome.ok is False
    assert "不存在" in outcome.error
    assert handler.elements["play_all"].clicks == 0


# ---------------------------------------------------------------------------
# Slice 4: 收藏 —— 收藏内搜索
# ---------------------------------------------------------------------------


def test_favourites_search_reveals_the_search_box_then_plays_the_matches(
    initialized_test_singletons,
):
    handler = _QQMusicHandlerFake(queue=QUEUE_TEXT)

    outcome = _driver(handler).start_playback(
        PlaybackRequest.favorites("谢安琪", variant=PlaybackVariant.SEARCH)
    )

    assert outcome.ok is True
    # 搜索框要滑动「全部播放」才露脸，先滑一下再点。
    assert len(handler.gesture_handler.swipes) == 1
    assert handler.elements["search_box"].clicks == 1
    assert handler.key_actions.clipboard == "谢安琪"
    assert handler.key_actions.pastes == 1
    assert handler.elements["play_favourite_search"].clicks == 1
    # 标题就是搜索词；全文里仍留着行首的歌手。
    assert outcome.title == "谢安琪"
    assert outcome.playlist == "谢安琪"
    assert outcome.extra["playlist"] == QUEUE_TEXT


def test_favourites_search_narrows_the_topic_to_the_song_name_only(
    initialized_test_singletons,
):
    handler = _QQMusicHandlerFake(queue=QUEUE_TEXT)

    outcome = _driver(handler).start_playback(
        PlaybackRequest.favorites("谢安琪", variant=PlaybackVariant.SEARCH)
    )

    assert outcome.topic == "喜帖街"


def test_favourites_search_reports_a_failure_when_the_search_box_never_appears(
    initialized_test_singletons,
):
    handler = _QQMusicHandlerFake(queue=QUEUE_TEXT, missing={"search_box"})

    outcome = _driver(handler).start_playback(
        PlaybackRequest.favorites("谢安琪", variant=PlaybackVariant.SEARCH)
    )

    assert outcome.ok is False
    assert handler.key_actions.pastes == 0


# ---------------------------------------------------------------------------
# Slice 5: 雷达
# ---------------------------------------------------------------------------


def test_radar_goes_home_and_opens_the_radar_stream(initialized_test_singletons):
    handler = _QQMusicHandlerFake()

    outcome = _driver(handler).start_playback(PlaybackRequest.radar(requester="小红"))

    assert outcome.ok is True
    assert handler.key_actions.switches == 1
    assert handler.home_visits == 1
    assert handler.radar_nav.clicks == 1
    assert (outcome.track.song, outcome.track.singer) == ("雷达电台", "O Radio")
    assert outcome.title == "O Radio"
    assert outcome.topic == "雷达电台"


def test_radar_reports_a_failure_when_the_radar_tab_is_missing(initialized_test_singletons):
    handler = _QQMusicHandlerFake(missing={"radar_nav"})

    outcome = _driver(handler).start_playback(PlaybackRequest.radar(requester="小红"))

    assert outcome.ok is False
    assert "radar" in outcome.error.lower()


@pytest.mark.parametrize("mode", [PlaybackMode.SINGER, PlaybackMode.ALBUM])
def test_modes_belonging_to_other_tickets_still_fail_loudly(mode, initialized_test_singletons):
    # PLAYLIST（#434）与 RADIO（#431）已各自交付，它们的编排测试见
    # tests/test_playlist_command_migration.py 与 tests/test_radio_seam.py。
    handler = _QQMusicHandlerFake(queue=QUEUE_TEXT)

    outcome = _driver(handler).start_playback(
        PlaybackRequest(mode=mode, query="任意", requester="小明")
    )

    assert outcome.ok is False
    assert handler.key_actions.switches == 0
