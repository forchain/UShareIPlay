from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import InvalidElementStateException

from ushareiplay.core.ui.gesture_handler import GestureHandler


class _Owner:
    def __init__(self, driver):
        self.driver = driver
        self.logger = MagicMock()
        self.config = {}


def _make_handler(driver):
    return GestureHandler(_Owner(driver))


def test_click_element_at_uses_mobile_click_gesture():
    driver = MagicMock()
    driver.get_window_size.return_value = {"width": 1080, "height": 2400}
    element = MagicMock()
    element.size = {"width": 200, "height": 80}
    element.location = {"x": 100, "y": 200}

    handler = _make_handler(driver)
    assert handler.click_element_at(element, x_ratio=0.5, y_ratio=0.5) is True

    driver.execute_script.assert_called_once_with(
        "mobile: clickGesture", {"x": 200, "y": 240}
    )


def test_click_element_at_falls_back_to_element_click_when_gestures_fail(monkeypatch):
    driver = MagicMock()
    driver.get_window_size.return_value = {"width": 1080, "height": 2400}
    driver.execute_script.side_effect = InvalidElementStateException("gesture failed")
    element = MagicMock()
    element.size = {"width": 200, "height": 80}
    element.location = {"x": 100, "y": 200}
    element.click.return_value = None

    class _FailingActions:
        def __init__(self, *_args, **_kwargs):
            self.w3c_actions = MagicMock()

        def perform(self):
            raise InvalidElementStateException("w3c failed")

    monkeypatch.setattr(
        "ushareiplay.core.ui.gesture_handler.ActionChains", _FailingActions
    )

    handler = _make_handler(driver)
    assert handler.click_element_at(element) is True
    element.click.assert_called_once_with()


def test_click_element_at_clamps_negative_y_ratio_to_screen_top():
    driver = MagicMock()
    driver.get_window_size.return_value = {"width": 1080, "height": 2400}
    element = MagicMock()
    element.size = {"width": 200, "height": 80}
    element.location = {"x": 100, "y": 40}

    handler = _make_handler(driver)
    assert handler.click_element_at(element, x_ratio=0.5, y_ratio=-1) is True

    driver.execute_script.assert_called_once_with(
        "mobile: clickGesture", {"x": 200, "y": 0}
    )


def test_clamp_click_coords_without_window_size_uses_legacy_floor():
    driver = MagicMock()
    driver.get_window_size.side_effect = RuntimeError("no session")
    handler = _make_handler(driver)

    assert handler._clamp_click_coords(120, -20) == (120, 60)


class FakeLogger:
    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class FakeDriver:
    def __init__(self):
        self.swipes = []

    def swipe(self, start_x, start_y, end_x, end_y, duration_ms):
        self.swipes.append((start_x, start_y, end_x, end_y, duration_ms))
        return None


def test_perform_swipe_uses_driver_swipe():
    driver = FakeDriver()
    handler = GestureHandler(
        SimpleNamespace(driver=driver, logger=FakeLogger(), config={})
    )

    assert handler.swipe(10, 20, 30, 40, duration_ms=250) is True
    assert driver.swipes == [(10, 20, 30, 40, 250)]


def test_scroll_container_uses_deliberate_swipe_duration():
    driver = MagicMock()
    driver.page_source = "<page />"
    handler = _make_handler(driver)
    handler.owner.element_finder = MagicMock()
    handler.owner.element_finder.wait_for_element_clickable.return_value = SimpleNamespace(
            location={"x": 0, "y": 0},
            size={"width": 100, "height": 100},
    )
    handler.owner.element_finder.find_child_element.return_value = None
    handler._perform_swipe = MagicMock(return_value=False)

    handler.scroll_container_until_element("message_content", "message_list")

    handler._perform_swipe.assert_called_once_with(50, 90, 50, 10, duration_ms=300)


def test_scroll_container_reads_target_attributes_from_page_source_cache():
    driver = MagicMock()
    driver.page_source = """
        <hierarchy>
          <node resource-id="message" content-desc="older" />
          <node resource-id="message" text="anchor" />
        </hierarchy>
    """
    handler = _make_handler(driver)
    handler.owner.config = {"elements": {"message_content": "message"}}
    handler.owner.element_finder = MagicMock()
    handler.owner.element_finder.wait_for_element_clickable.return_value = SimpleNamespace(
        location={"x": 0, "y": 0},
        size={"width": 100, "height": 100},
    )
    older = MagicMock()
    anchor = MagicMock()
    handler.owner.element_finder.find_child_elements.return_value = [older, anchor]
    handler.owner.element_finder.try_get_attribute.side_effect = lambda element, attribute: {
        (older, "content-desc"): "older",
        (anchor, "text"): "anchor",
    }.get((element, attribute))

    result = handler.scroll_container_until_element(
        "message_content",
        "message_list",
        direction="down",
        attribute_name="content-desc|text",
        attribute_value="anchor",
    )

    assert result[0] == "message_content"
    assert result[1] is anchor
    assert result[2] == ["anchor", "older"]
    handler.owner.element_finder.wait_for_element_clickable.assert_called_once_with("message_list")
    handler.owner.element_finder.wait_for_element.assert_not_called()
    handler.owner.element_finder.find_child_element.assert_not_called()


def test_scroll_container_returns_the_visible_element_matching_attribute_value():
    driver = MagicMock()
    driver.page_source = """
        <hierarchy>
          <node resource-id="online-name" text="Joyer" />
          <node resource-id="online-name" text="Outlier" />
        </hierarchy>
    """
    handler = _make_handler(driver)
    handler.owner.config = {"elements": {"online_user": "online-name"}}
    handler.owner.element_finder = MagicMock()
    container = SimpleNamespace(
        location={"x": 0, "y": 0},
        size={"width": 100, "height": 100},
    )
    joyer = MagicMock(text="Joyer")
    outlier = MagicMock(text="Outlier")
    handler.owner.element_finder.wait_for_element_clickable.return_value = container
    handler.owner.element_finder.find_child_elements.return_value = [joyer, outlier]
    handler.owner.element_finder.try_get_attribute.side_effect = (
        lambda element, attribute: element.text if attribute == "text" else None
    )

    result = handler.scroll_container_until_element(
        "online_user",
        "online_users",
        attribute_name="text",
        attribute_value="Outlier",
    )

    assert result[0] == "online_user"
    assert result[1] is outlier


def test_swipe_until_element_returns_immediately_if_already_visible():
    driver = MagicMock()
    handler = _make_handler(driver)
    handler.owner.element_finder = MagicMock()
    target_element = MagicMock()
    handler.owner.element_finder.try_find_element.return_value = target_element

    result = handler.swipe_until_element("target_key", max_swipes=5)

    assert result is target_element
    handler.owner.element_finder.try_find_element.assert_called_once_with("target_key", log=False)
    driver.get_window_size.assert_not_called()


def test_swipe_until_element_swipes_screen_center_and_finds_element():
    driver = MagicMock()
    driver.get_window_size.return_value = {"width": 720, "height": 1480}
    handler = _make_handler(driver)
    handler.owner.element_finder = MagicMock()
    target_element = MagicMock()

    # 第一次查找 None，第一次滑动后找到
    handler.owner.element_finder.try_find_element.side_effect = [None, target_element]
    handler.swipe = MagicMock(return_value=True)

    result = handler.swipe_until_element("target_key", direction="up", max_swipes=3)

    assert result is target_element
    handler.swipe.assert_called_once_with(360, int(1480 * 0.75), 360, int(1480 * 0.35), duration_ms=300)


def test_swipe_until_element_returns_none_when_max_swipes_exhausted():
    driver = MagicMock()
    driver.get_window_size.return_value = {"width": 720, "height": 1480}
    handler = _make_handler(driver)
    handler.owner.element_finder = MagicMock()
    handler.owner.element_finder.try_find_element.return_value = None
    handler.swipe = MagicMock(return_value=True)

    result = handler.swipe_until_element("target_key", direction="up", max_swipes=2)

    assert result is None
    assert handler.swipe.call_count == 2


_RENDERED_TAB_STRIP = (
    '<hierarchy><node resource-id="playlist" content-desc="歌单 按钮" /></hierarchy>'
)


class _SlowRenderingDriver:
    """模拟「UI 渲染慢」：等容器的那一刻，页面才把目标渲染出来。

    等容器之前页面里没有目标（快照是旧的）；等容器之后目标就在视口里。
    """

    def __init__(self):
        self.ready = False

    @property
    def page_source(self):
        if self.ready:
            return _RENDERED_TAB_STRIP
        return "<hierarchy></hierarchy>"


class _FakePageSourceDriver:
    """按顺序吐出 page source；用完以后重复最后一份。"""

    def __init__(self, page_sources):
        self._page_sources = list(page_sources)
        self._last = "<hierarchy></hierarchy>"

    @property
    def page_source(self):
        if self._page_sources:
            self._last = self._page_sources.pop(0)
        return self._last


def _tab_strip_handler(driver, tab_element=None):
    """构造一个「横向 tab 条」场景的 handler。"""
    handler = _make_handler(driver)
    handler.owner.config = {"elements": {"playlist_tab": "playlist"}}
    handler.owner.element_finder = MagicMock()
    handler.owner.element_finder.wait_for_element_clickable.return_value = SimpleNamespace(
        location={"x": 0, "y": 0},
        size={"width": 720, "height": 120},
    )
    handler.owner.element_finder.find_child_elements.return_value = (
        [tab_element] if tab_element is not None else []
    )
    return handler


def test_scroll_container_does_not_swipe_when_target_appeared_while_container_loaded():
    """UI 渲染慢：容器等到时目标已经在视口里 —— 不许再滑一次把它推出视口。

    旧实现先取 page source 快照（那时 UI 还没渲染好，快照里没有目标），
    再等容器；等容器期间目标渲染出来了却没人复查，直接滑一次，把刚出现的
    目标推出了视口，之后再也找不回来。
    """
    target = MagicMock()
    ui = _SlowRenderingDriver()
    handler = _tab_strip_handler(ui, tab_element=target)
    container = handler.owner.element_finder.wait_for_element_clickable.return_value

    def wait_for_container(*_args, **_kwargs):
        ui.ready = True  # 等容器期间 UI 渲染完成，目标露脸
        return container

    handler.owner.element_finder.wait_for_element_clickable.side_effect = wait_for_container
    swipes = []

    def fake_swipe(sx, sy, ex, ey, duration_ms=300):
        swipes.append((sx, sy, ex, ey))
        return True

    handler._perform_swipe = fake_swipe
    # 一旦滑过一次，目标就被推出视口（横向 tab 条滑出屏幕即从层级里消失）
    handler.owner.element_finder.find_child_elements.side_effect = lambda *_: (
        [] if swipes else [target]
    )

    key, element, _values = handler.scroll_container_until_element(
        "playlist_tab", "music_tabs", direction="left", max_swipes=20
    )

    assert key == "playlist_tab"
    assert element is target
    assert swipes == []


def test_scroll_container_searches_opposite_direction_when_target_was_pushed_away():
    """单向滚动会把目标推出视口；扫不到时反方向再扫一遍才能捞回来。"""
    target = MagicMock()
    driver = _FakePageSourceDriver([_RENDERED_TAB_STRIP])
    handler = _tab_strip_handler(driver, tab_element=None)
    swipes = []

    def fake_swipe(sx, sy, ex, ey, duration_ms=300):
        swipes.append((sx, sy, ex, ey))
        return True

    handler._perform_swipe = fake_swipe

    def find_children(*_args):
        # 目标只在「往回滚」（向右滑）之后才露脸
        if swipes and swipes[-1][0] < swipes[-1][2]:
            return [target]
        return []

    handler.owner.element_finder.find_child_elements.side_effect = find_children

    key, element, _values = handler.scroll_container_until_element(
        "playlist_tab", "music_tabs", direction="left", max_swipes=20
    )

    assert key == "playlist_tab"
    assert element is target
    # 兜底扫描必须真的往回滚过
    assert swipes[-1][0] < swipes[-1][2]
