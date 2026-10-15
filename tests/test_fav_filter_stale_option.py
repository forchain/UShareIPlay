"""#425：收藏筛选页的筛选项必须「重新定位后再点」。

回归点是筛选器那条 raw XPath（筛选项文案由用户关键字拼出来，`config.yaml` 里没有
对应元素 key）：点按前后的页面重排会让元素句柄变成 stale，拿着旧句柄点下去只会静默
失败 —— 表现为「筛选没生效，却播了全部收藏」。

筛选编排本身已随 `:fav type <关键字>` 迁进 `QQMusicUIDriver.start_playback()`，因此
这两条回归也改从驱动上观察：请求里给出形态与关键字，断言返回的 `PlaybackOutcome`
说明筛选真的生效了，而不只是「没抛异常」。
"""

from types import SimpleNamespace

import pytest
from selenium.common.exceptions import StaleElementReferenceException

from ushareiplay.managers.playback.models import PlaybackRequest, PlaybackVariant
from ushareiplay.managers.playback.qq_music_ui_driver import QQMusicUIDriver


class _Element:
    def __init__(self, text="", stale_clicks=0, stale_enabled_checks=0):
        self.text = text
        self.stale_clicks = stale_clicks
        self.stale_enabled_checks = stale_enabled_checks
        self.clicks = 0

    def is_displayed(self):
        return True

    def is_enabled(self):
        if self.stale_enabled_checks:
            self.stale_enabled_checks -= 1
            raise StaleElementReferenceException("stale enabled check")
        return True

    def click(self):
        self.clicks += 1
        if self.stale_clicks:
            self.stale_clicks -= 1
            raise StaleElementReferenceException("stale option")

    def find_elements(self, _by, _value):
        return []


class _FavouriteFilterXPathDriver:
    """筛选器那条 raw XPath 的定位替身：第一次交出旧句柄，之后交出可用的新句柄。"""

    def __init__(self, option_stale, option_fresh, confirm):
        self.option_stale = option_stale
        self.option_fresh = option_fresh
        self.confirm = confirm
        self.option_lookups = 0
        self.locators = []

    def find_element(self, _by, xpath):
        self.locators.append(xpath)
        if "确定（" in xpath:
            return self.confirm
        self.option_lookups += 1
        return self.option_stale if self.option_lookups == 1 else self.option_fresh


class _ElementFinder:
    def __init__(self, elements):
        self.elements = elements
        self.requested = []

    def _find(self, key):
        self.requested.append(key)
        return self.elements.get(key)

    def try_find_element(self, key, log=False):
        return self._find(key)

    def wait_for_element_clickable(self, key, timeout=None):
        return self._find(key)

    def wait_for_element(self, key, timeout=None):
        return self._find(key)


class _HandlerFake:
    def __init__(self, option_stale, option_fresh, confirm):
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
            debug=lambda *_a, **_k: None,
        )
        self.filter_button = _Element()
        self.play_all = _Element()
        self._element_finder = _ElementFinder(
            {
                "filter_favourite": self.filter_button,
                "play_all": self.play_all,
            }
        )
        self.key_actions = SimpleNamespace(switch_to_app=lambda: True)
        self.driver = _FavouriteFilterXPathDriver(option_stale, option_fresh, confirm)

    @property
    def element_finder(self):
        return self._element_finder

    def open_favorites_entry(self, timeout=10):
        return None

    def get_playlist_info(self):
        return {"playlist": "喜帖街 - 谢安琪"}

    def navigate_to_home(self):
        return True


def _filter_outcome(handler):
    request = PlaybackRequest.favorites("英语", variant=PlaybackVariant.FILTER)
    return QQMusicUIDriver(handler).start_playback(request)


def test_favourites_filter_refinds_the_option_when_the_click_goes_stale(
    initialized_test_singletons,
):
    """第一次点下去时页面正好重排：旧句柄点不动，必须重新定位再点一次。"""
    option_stale = _Element(stale_clicks=1)
    option_fresh = _Element()
    handler = _HandlerFake(option_stale, option_fresh, _Element(text="确定（12首）"))

    outcome = _filter_outcome(handler)

    assert outcome.ok is True
    # 重新定位过：旧句柄点了一次、新句柄点了一次，命中数也读回来了。
    assert handler.driver.option_lookups == 2
    assert option_stale.clicks == 1
    assert option_fresh.clicks == 1
    assert outcome.extra["count"] == 12
    # 英语在房间里叫「英乐」，说明确实走到了筛选那条路。
    assert outcome.title == "英乐"


def test_favourites_filter_refinds_the_option_when_the_clickable_check_goes_stale(
    initialized_test_singletons,
):
    """可点性检查本身就撞上重排：连点都不该点，直接换一个新句柄。"""
    option_stale = _Element(stale_enabled_checks=1)
    option_fresh = _Element()
    handler = _HandlerFake(option_stale, option_fresh, _Element(text="确定（12首）"))

    outcome = _filter_outcome(handler)

    assert outcome.ok is True
    assert option_stale.clicks == 0
    assert option_fresh.clicks == 1
    assert outcome.extra["count"] == 12


def test_favourites_filter_looks_the_option_up_by_the_users_own_keyword(
    initialized_test_singletons,
):
    """筛选项没有固定元素 key，只能按用户原样输入的关键字现拼 XPath。"""
    option_stale = _Element()
    option_fresh = _Element()
    handler = _HandlerFake(option_stale, option_fresh, _Element(text="确定（12首）"))

    _filter_outcome(handler)

    assert handler.driver.locators[0] == '//android.widget.TextView[@text="英语"]'


@pytest.mark.parametrize("keyword,expected_title", [("粤语", "粤音"), ("英语", "英乐"), ("流行", "流行")])
def test_favourites_filter_names_the_room_after_the_filtered_playlist(
    keyword, expected_title, initialized_test_singletons
):
    """粤语/英语在房间里用简称，其余关键字原样当房间名。"""
    handler = _HandlerFake(
        _Element(), _Element(), _Element(text="确定（12首）")
    )

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.favorites(keyword, variant=PlaybackVariant.FILTER)
    )

    assert outcome.title == expected_title
