from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from ushareiplay.handlers.qq_music_handler import QQMusicHandler


class _Logger:
    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []

    def info(self, msg):
        self.infos.append(msg)

    def warning(self, msg):
        self.warnings.append(msg)

    def error(self, msg):
        self.errors.append(msg)


class _Element:
    def __init__(self, name="element"):
        self.name = name
        self.clicks = 0

    def click(self):
        self.clicks += 1


def _create_handler(elements=None):
    handler = QQMusicHandler.__new__(QQMusicHandler)
    handler.logger = _Logger()
    handler.config = {
        "elements": elements
        or {
            "singer_tab": "//singer",
            "album_tab": "//album",
            "playlist_tab": "//playlist",
            "song_tab": "//song",
            "lyrics_tab": "//lyrics",
            "radio_tab": "//radio",
            "music_tabs": "//container",
        },
        "qq_music": {"tab_max_swipes": 10},
    }
    handler.element_finder = SimpleNamespace()
    handler.gesture_handler = SimpleNamespace()
    return handler


def test_select_tab_when_already_visible_clicks_without_swiping():
    handler = _create_handler()
    tab_elem = _Element("singer_tab")

    handler.element_finder.try_find_element = MagicMock(return_value=tab_elem)
    handler.gesture_handler.scroll_container_until_element = MagicMock()

    result = handler.select_tab("singer")

    assert result is True
    assert tab_elem.clicks == 1
    handler.element_finder.try_find_element.assert_called_once_with("singer_tab")
    handler.gesture_handler.scroll_container_until_element.assert_not_called()


def test_select_tab_normalizes_aliases_and_tab_suffixes():
    handler = _create_handler()

    for tab_input, expected_key in [
        ("singer", "singer_tab"),
        ("singer_tab", "singer_tab"),
        ("album", "album_tab"),
        ("playlist", "playlist_tab"),
        ("song", "song_tab"),
        ("songs", "song_tab"),
        ("lyrics", "lyrics_tab"),
        ("radio", "radio_tab"),
        ("歌手", "singer_tab"),
        ("专辑", "album_tab"),
        ("歌单", "playlist_tab"),
        ("歌曲", "song_tab"),
        ("电台", "radio_tab"),
    ]:
        tab_elem = _Element(expected_key)
        handler.element_finder.try_find_element = MagicMock(return_value=tab_elem)
        handler.gesture_handler.scroll_container_until_element = MagicMock()

        assert handler.select_tab(tab_input) is True
        handler.element_finder.try_find_element.assert_called_with(expected_key)
        assert tab_elem.clicks == 1


def test_select_tab_scrolls_container_when_not_immediately_visible():
    handler = _create_handler()
    tab_elem = _Element("album_tab")

    # Not visible before the swipe, located again after it
    handler.element_finder.try_find_element = MagicMock(side_effect=[None, tab_elem])
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=("album_tab", tab_elem, [])
    )

    result = handler.select_tab("album")

    assert result is True
    assert tab_elem.clicks == 1
    handler.gesture_handler.scroll_container_until_element.assert_called_once_with(
        "album_tab",
        "music_tabs",
        "left",
        max_swipes=10,
    )


def test_select_tab_clicks_relocated_tab_when_scroll_helper_returns_the_container():
    """滚动助手对绝对 XPath 的解析可能返回容器；此时必须点重新定位到的 tab，而不是容器。"""
    handler = _create_handler()
    container_marker = _Element("container_marker")
    tab_elem = _Element("lyrics_tab")

    handler.element_finder.try_find_element = MagicMock(side_effect=[None, tab_elem])
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=("lyrics_tab", container_marker, [])
    )

    assert handler.select_tab("lyrics") is True
    assert tab_elem.clicks == 1
    assert container_marker.clicks == 0


def test_select_tab_fallback_find_element_after_scroll_returns_element_none():
    handler = _create_handler()
    tab_elem = _Element("playlist_tab")

    # scroll_container_until_element returned None for element, but subsequent try_find_element locates it
    handler.element_finder.try_find_element = MagicMock(side_effect=[None, tab_elem])
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=("playlist_tab", None, [])
    )

    result = handler.select_tab("playlist")

    assert result is True
    assert tab_elem.clicks == 1


def test_select_tab_falls_back_to_scroll_helper_element_when_relocation_fails():
    """重新定位失败时仍点助手返回的元素，不比旧行为更差。"""
    handler = _create_handler()
    tab_elem = _Element("radio_tab")

    handler.element_finder.try_find_element = MagicMock(side_effect=[None, None])
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=("radio_tab", tab_elem, [])
    )

    assert handler.select_tab("radio") is True
    assert tab_elem.clicks == 1


def test_select_tab_returns_false_when_tab_missing_after_scrolling():
    handler = _create_handler()

    handler.element_finder.try_find_element = MagicMock(return_value=None)
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=(None, None, [])
    )

    result = handler.select_tab("radio")

    assert result is False
    assert len(handler.logger.errors) >= 1
    assert "radio" in handler.logger.errors[0]


def test_select_tab_handles_exception_without_unhandled_crash():
    handler = _create_handler()

    handler.element_finder.try_find_element = MagicMock(side_effect=RuntimeError("UI connection severed"))

    result = handler.select_tab("singer")

    assert result is False
    assert len(handler.logger.errors) >= 1
    assert "UI connection severed" in handler.logger.errors[0]


def test_select_tab_custom_container_and_swipes():
    handler = _create_handler(elements={"custom_tab": "//custom", "custom_strip": "//strip"})
    tab_elem = _Element("custom_tab")

    handler.element_finder.try_find_element = MagicMock(return_value=None)
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=("custom_tab", tab_elem, [])
    )

    result = handler.select_tab("custom_tab", container_key="custom_strip", max_swipes=5)

    assert result is True
    assert tab_elem.clicks == 1
    handler.gesture_handler.scroll_container_until_element.assert_called_once_with(
        "custom_tab",
        "custom_strip",
        "left",
        max_swipes=5,
    )


def test_select_tab_song_tab_swipes_back_to_the_start_of_the_strip():
    """单曲 tab 靠前，搜索页停在别的分类时要向回滚（right），这是原 select_song_tab 的唯一特例。"""
    handler = _create_handler()
    tab_elem = _Element("song_tab")

    handler.element_finder.try_find_element = MagicMock(return_value=None)
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=("song_tab", tab_elem, [])
    )

    result = handler.select_tab("song", direction="right")

    assert result is True
    assert tab_elem.clicks == 1
    handler.gesture_handler.scroll_container_until_element.assert_called_once_with(
        "song_tab",
        "music_tabs",
        "right",
        max_swipes=10,
    )


def test_select_tab_falls_back_to_builtin_swipe_limit_when_config_is_absent():
    handler = _create_handler()
    del handler.config["qq_music"]["tab_max_swipes"]
    tab_elem = _Element("album_tab")

    handler.element_finder.try_find_element = MagicMock(return_value=None)
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=("album_tab", tab_elem, [])
    )

    assert handler.select_tab("album") is True
    handler.gesture_handler.scroll_container_until_element.assert_called_once_with(
        "album_tab",
        "music_tabs",
        "left",
        max_swipes=10,
    )


def test_select_tab_reads_swipe_limit_from_qq_music_config():
    handler = _create_handler()
    handler.config["qq_music"]["tab_max_swipes"] = 7
    tab_elem = _Element("album_tab")

    handler.element_finder.try_find_element = MagicMock(return_value=None)
    handler.gesture_handler.scroll_container_until_element = MagicMock(
        return_value=("album_tab", tab_elem, [])
    )

    result = handler.select_tab("album")

    assert result is True
    handler.gesture_handler.scroll_container_until_element.assert_called_once_with(
        "album_tab",
        "music_tabs",
        "left",
        max_swipes=7,
    )


def test_select_tab_recovers_from_stale_element_reference():
    from selenium.common import StaleElementReferenceException

    handler = _create_handler()
    stale_elem = MagicMock()
    stale_elem.click.side_effect = StaleElementReferenceException("element is stale")

    fresh_elem = _Element("refreshed_tab")

    # First lookup returns stale_elem, second lookup (during recovery) returns fresh_elem
    handler.element_finder.try_find_element = MagicMock(side_effect=[stale_elem, fresh_elem])

    result = handler.select_tab("singer")

    assert result is True
    assert fresh_elem.clicks == 1


def test_select_tab_handles_stale_element_when_refresh_fails():
    from selenium.common import StaleElementReferenceException

    handler = _create_handler()
    stale_elem = MagicMock()
    stale_elem.click.side_effect = StaleElementReferenceException("element is stale")

    # First lookup returns stale_elem, second lookup (recovery) returns None
    handler.element_finder.try_find_element = MagicMock(side_effect=[stale_elem, None])

    result = handler.select_tab("singer")

    assert result is False
    assert len(handler.logger.errors) >= 1

