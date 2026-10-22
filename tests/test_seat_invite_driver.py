"""SeatInviteDriver 的测试：「邀请入座」底部弹窗的打开判定、列表分页、状态识别与安全关闭。

替身沿用 tests/seat_fixtures.py 的形状（raw WebElement 的 find_element 契约、
真实 config.yaml 的元素 key），只在本文件里补一个能认出「邀请入座」弹窗元素的
查找器 —— 不去改共用替身，免得和别的票抢同一个文件。

铁律在本文件里被钉死：关弹窗只点界面上的 X，**一次 press_back 都不许有** ——
派对房间里一次盲按返回键就是退出派对房间。
"""

from unittest.mock import MagicMock

import pytest

from tests.seat_fixtures import ClickableNode, FakeElementFinder, soul_elements

from ushareiplay.managers.seat_manager.seat_invite_driver import (
    SeatInviteDriver,
    SeatInviteRow,
)

ROW_KEY = "seat_invite_row"
NAME_KEY = "seat_invite_name"
OPERATION_KEY = "seat_invite_operation"
CLOSE_KEY = "seat_invite_close"
PANEL_KEY = "seat_invite_panel"


class InviteRow:
    """弹窗里的一行（raw WebElement 形状）：子节点按 resource-id 索引。"""

    def __init__(self, name, operation, elements=None):
        elements = elements or soul_elements()
        self.elements = elements
        self.name = name
        self.operation = operation
        self.name_node = ClickableNode(name)
        self.operation_node = ClickableNode(operation)
        self.children = {
            elements[NAME_KEY]: self.name_node,
            elements[OPERATION_KEY]: self.operation_node,
        }

    def find_element(self, _by, value):
        child = self.children.get(value)
        if child is None:
            raise KeyError(value)
        return child


class NamelessRow(InviteRow):
    """一行读不出昵称的行（昵称节点缺失或为空）。"""

    def __init__(self, elements=None):
        elements = elements or soul_elements()
        self.elements = elements
        self.name = ""
        self.operation = "邀请"
        self.name_node = ClickableNode("")
        self.operation_node = ClickableNode("邀请")
        self.children = {elements[OPERATION_KEY]: self.operation_node}


class InviteSheetFinder(FakeElementFinder):
    """能认出「邀请入座」弹窗元素的查找器：按真实 config key 解析。

    pages 是「每一页可见的行」；滑动一次前进一页。pages 为空表示弹窗根本没开。
    """

    def __init__(self, elements, pages=None, close_button=None, panel=None, **kwargs):
        super().__init__(elements, **kwargs)
        self.pages = pages or []
        self.page_index = 0
        self.close_button = close_button
        self.panel = panel

    @property
    def current_page(self):
        if not self.pages:
            return []
        return self.pages[min(self.page_index, len(self.pages) - 1)]

    def advance(self):
        """滑动一次：前进一页（到底了就是没变化）。"""
        self.page_index = min(self.page_index + 1, len(self.pages) - 1)

    def find_elements(self, element_key):
        if element_key == ROW_KEY:
            return list(self.current_page)
        return super().find_elements(element_key)

    def find_child_elements(self, parent, element_key):
        """在弹窗列表容器里找行（与生产 ElementFinder.find_child_elements 同形）。"""
        if element_key == ROW_KEY:
            return list(self.current_page)
        return []

    def find_child_element(self, parent, element_key, log_failure=True):
        if element_key in (NAME_KEY, OPERATION_KEY):
            try:
                return parent.find_element(None, self.elements[element_key])
            except Exception:
                return None
        return super().find_child_element(parent, element_key, log_failure=log_failure)

    def try_find_element(self, element_key, log=False, clickable=False):
        if element_key == CLOSE_KEY:
            return self.close_button
        if element_key == PANEL_KEY:
            return self.panel
        return super().try_find_element(element_key, log=log, clickable=clickable)


def make_invite_handler(pages=None, close_button=None, panel=None, swipe_advances=True):
    """一个装着「邀请入座」弹窗的 handler。"""
    handler = MagicMock()
    handler.logger = MagicMock()
    handler.key_actions = MagicMock()
    handler.gesture_handler = MagicMock()
    handler.config = {"elements": soul_elements()}
    finder = InviteSheetFinder(
        soul_elements(), pages=pages, close_button=close_button, panel=panel
    )
    handler.element_finder = finder
    if swipe_advances:
        handler.gesture_handler.swipe.side_effect = lambda *args, **kwargs: finder.advance()
    handler.gesture_handler.swipe.return_value = True
    return handler


# ---------------------------------------------------------------------------
# 配置：选择器必须集中在 config.yaml
# ---------------------------------------------------------------------------


def test_config_defines_the_invite_sheet_selectors():
    """弹窗选择器只在 config.yaml 里定义，Python 侧不得自带 resource-id。"""
    elements = soul_elements()

    for key in (ROW_KEY, NAME_KEY, OPERATION_KEY, CLOSE_KEY, PANEL_KEY):
        assert key in elements, key
        assert isinstance(elements[key], str) and elements[key].strip(), key


# ---------------------------------------------------------------------------
# 打开判定
# ---------------------------------------------------------------------------


def test_is_open_is_false_when_no_invite_row_is_readable():
    """弹窗没开：读不到任何邀请行就不算开。"""
    driver = SeatInviteDriver(make_invite_handler(pages=[]))

    assert driver.is_open() is False


async def test_wait_until_open_times_out_when_the_sheet_never_opens():
    handler = make_invite_handler(pages=[])
    driver = SeatInviteDriver(handler)

    assert await driver.wait_until_open(timeout=0.2) is False
    handler.gesture_handler.swipe.assert_not_called()


async def test_wait_until_open_is_true_once_a_row_is_readable():
    driver = SeatInviteDriver(make_invite_handler(pages=[[InviteRow("Alice", "邀请")]]))

    assert await driver.wait_until_open(timeout=0.5) is True


def test_is_open_without_a_handler_is_false():
    assert SeatInviteDriver(None).is_open() is False


# ---------------------------------------------------------------------------
# 读行：昵称 + 操作按钮文案
# ---------------------------------------------------------------------------


def test_read_rows_returns_the_nickname_and_the_operation_text():
    driver = SeatInviteDriver(
        make_invite_handler(pages=[[InviteRow("Alice", "邀请"), InviteRow("Bob", "已上座")]])
    )

    rows = driver.read_rows()

    assert [(r.name, r.operation) for r in rows] == [("Alice", "邀请"), ("Bob", "已上座")]


def test_read_rows_skips_rows_without_a_readable_nickname():
    """读不出昵称的行没有意义（比对用的是可见昵称），整行跳过。"""
    driver = SeatInviteDriver(
        make_invite_handler(pages=[[NamelessRow(), InviteRow("Alice", "邀请")]])
    )

    rows = driver.read_rows()

    assert [r.name for r in rows] == ["Alice"]


def test_read_rows_without_an_element_finder_is_empty():
    handler = make_invite_handler(pages=[[InviteRow("Alice", "邀请")]])
    handler.element_finder = None
    driver = SeatInviteDriver(handler)

    assert driver.read_rows() == []


def test_read_rows_is_scoped_to_the_invite_panel_when_it_can_be_found():
    """行查找收敛到弹窗自己的列表容器：页面别处的同名容器不该混进来。"""
    panel = MagicMock()
    handler = make_invite_handler(pages=[[InviteRow("Alice", "邀请")]], panel=panel)
    finder = handler.element_finder

    def _page_wide(element_key):
        if element_key == ROW_KEY:
            # 页面别处还有一个同 resource-id 的容器（别的浮层）
            return list(finder.current_page) + [InviteRow("路人", "邀请")]
        return finder.find_elements(element_key)

    finder.find_elements = _page_wide
    driver = SeatInviteDriver(handler)

    rows = driver.read_rows()

    assert [row.name for row in rows] == ["Alice"]


def test_read_rows_falls_back_to_the_page_wide_lookup_without_the_panel():
    """弹窗容器读不到（尽力而为的结构化 XPath）：退回全屏查找。"""
    handler = make_invite_handler(pages=[[InviteRow("Alice", "邀请")]])
    driver = SeatInviteDriver(handler)

    rows = driver.read_rows()

    assert [row.name for row in rows] == ["Alice"]


@pytest.mark.parametrize(
    "operation, invitable",
    [
        ("邀请", True),
        ("上座", True),
        ("已上座", False),
        ("", False),
    ],
)
def test_invitable_is_derived_from_the_operation_text(operation, invitable):
    """「邀请」/「上座」可点，「已上座」说明人已经在座上，不可点。"""
    driver = SeatInviteDriver(
        make_invite_handler(pages=[[InviteRow("Alice", operation)]])
    )

    row = driver.read_rows()[0]

    assert row.invitable is invitable
    assert row.operation == operation


# ---------------------------------------------------------------------------
# 检索：翻页
# ---------------------------------------------------------------------------


async def test_find_row_finds_a_target_that_is_only_on_the_second_page():
    """目标不在第一页：翻一页再找。"""
    handler = make_invite_handler(
        pages=[[InviteRow("Alice", "邀请")], [InviteRow("Bob", "邀请")]]
    )
    driver = SeatInviteDriver(handler)

    row = await driver.find_row("Bob")

    assert row is not None
    assert row.name == "Bob"
    handler.gesture_handler.swipe.assert_called_once()


async def test_find_row_gives_up_when_the_list_stops_changing():
    """滑了一页但列表一模一样：没有更多数据了，别无限滑下去。"""
    handler = make_invite_handler(pages=[[InviteRow("Alice", "邀请")]])
    driver = SeatInviteDriver(handler)

    row = await driver.find_row("Bob")

    assert row is None
    # 只滑了一次就停手（列表没变化）
    assert handler.gesture_handler.swipe.call_count == 1


async def test_find_row_returns_none_when_the_target_is_absent_entirely():
    handler = make_invite_handler(
        pages=[[InviteRow("Alice", "邀请")], [InviteRow("Bob", "已上座")]]
    )
    driver = SeatInviteDriver(handler)

    assert await driver.find_row("Carol") is None


async def test_find_row_returns_none_when_the_sheet_is_closed():
    driver = SeatInviteDriver(make_invite_handler(pages=[]))

    assert await driver.find_row("Alice") is None


async def test_find_row_keeps_paging_when_a_page_is_still_rendering():
    """半渲染的一页（读得到行、读不出昵称）不算「弹窗没了」：翻页继续找。

    昵称还没渲染出来就下结论，会把一个**确实在列表里**的人报成「未在邀请列表中
    找到」—— 那是一个假失败。
    """
    handler = make_invite_handler(
        pages=[[NamelessRow()], [InviteRow("Bob", "邀请")]]
    )
    driver = SeatInviteDriver(handler)

    row = await driver.find_row("Bob")

    assert row is not None
    assert row.name == "Bob"
    handler.gesture_handler.swipe.assert_called_once()


async def test_find_row_gives_up_when_every_page_stays_half_rendered():
    """每一页都半渲染：翻页签名不变就停手，别无限滑下去。"""
    handler = make_invite_handler(pages=[[NamelessRow()]])
    driver = SeatInviteDriver(handler)

    assert await driver.find_row("Bob") is None
    assert handler.gesture_handler.swipe.call_count == 1


async def test_find_row_scrolls_inside_the_invite_list_area():
    """滑动落在弹窗列表区域内，不能滑到房间界面上。"""
    panel = MagicMock()
    panel.rect = {"x": 0, "y": 1000, "width": 1080, "height": 700}
    handler = make_invite_handler(
        pages=[[InviteRow("Alice", "邀请")], [InviteRow("Bob", "邀请")]], panel=panel
    )
    driver = SeatInviteDriver(handler)

    await driver.find_row("Bob")

    start_x, start_y, end_x, end_y = handler.gesture_handler.swipe.call_args.args[:4]
    assert start_x == end_x
    assert start_y > end_y  # 向上滑才看得到后面的人
    assert 1000 <= start_y <= 1700
    assert 1000 <= end_y <= 1700


async def test_find_row_without_a_gesture_handler_gives_up():
    handler = make_invite_handler(pages=[[InviteRow("Alice", "邀请")]])
    handler.gesture_handler = None
    driver = SeatInviteDriver(handler)

    assert await driver.find_row("Bob") is None


# ---------------------------------------------------------------------------
# 点击「邀请」
# ---------------------------------------------------------------------------


def test_click_invite_clicks_the_operation_button():
    handler = make_invite_handler(pages=[[InviteRow("Alice", "邀请")]])
    driver = SeatInviteDriver(handler)
    row = driver.read_rows()[0]

    assert driver.click_invite(row) is True
    assert row.operation_element.clicked is True


def test_click_invite_refuses_a_row_that_is_already_seated():
    """「已上座」的人不能再点一次邀请 —— 点了也只会得到一个错。"""
    handler = make_invite_handler(pages=[[InviteRow("Alice", "已上座")]])
    driver = SeatInviteDriver(handler)
    row = driver.read_rows()[0]

    assert driver.click_invite(row) is False
    assert row.operation_element.clicked is False


def test_click_invite_without_a_row_is_false():
    driver = SeatInviteDriver(make_invite_handler(pages=[]))

    assert driver.click_invite(None) is False


# ---------------------------------------------------------------------------
# 关闭弹窗：只点 X，严禁 press_back
# ---------------------------------------------------------------------------


def test_close_clicks_the_x_button_and_never_presses_back():
    """派对房间里一次盲按返回键就是退出派对房间：关弹窗只认界面上的 X。"""
    close_button = ClickableNode("")
    handler = make_invite_handler(
        pages=[[InviteRow("Alice", "邀请")]], close_button=close_button
    )
    driver = SeatInviteDriver(handler)

    assert driver.close() is True
    assert close_button.clicked is True
    handler.key_actions.press_back.assert_not_called()


def test_close_reports_failure_when_there_is_no_x_button():
    handler = make_invite_handler(pages=[[InviteRow("Alice", "邀请")]])
    driver = SeatInviteDriver(handler)

    assert driver.close() is False
    handler.key_actions.press_back.assert_not_called()


def test_close_does_not_click_the_x_when_there_is_no_evidence_of_the_sheet():
    """`ivClose` 是全 App 共用的 X：弹窗不在屏幕上时点它就是关别人的浮层。"""
    close_button = ClickableNode("")
    handler = make_invite_handler(pages=[], close_button=close_button)
    driver = SeatInviteDriver(handler)

    assert driver.close() is False
    assert close_button.clicked is False
    handler.key_actions.press_back.assert_not_called()


def test_close_clicks_the_x_when_only_the_panel_is_on_screen():
    """行还没读出来不算「弹窗不在」：弹窗自己的列表容器在，就是证据。"""
    close_button = ClickableNode("")
    panel = MagicMock()
    handler = make_invite_handler(pages=[], close_button=close_button, panel=panel)
    driver = SeatInviteDriver(handler)

    assert driver.close() is True
    assert close_button.clicked is True


def test_is_open_is_true_when_only_the_panel_is_on_screen():
    """弹窗刚弹出来、行还没渲染完：容器在就算开着。"""
    panel = MagicMock()
    handler = make_invite_handler(pages=[], panel=panel)
    driver = SeatInviteDriver(handler)

    assert driver.is_open() is True


def test_close_without_a_handler_is_false():
    assert SeatInviteDriver(None).close() is False


# ---------------------------------------------------------------------------
# 降级：任何方法都不许把异常甩给调用方
# ---------------------------------------------------------------------------


def test_driver_without_a_handler_degrades_gracefully():
    driver = SeatInviteDriver(None)

    assert driver.is_open() is False
    assert driver.read_rows() == []
    assert driver.close() is False
    assert driver.click_invite(SeatInviteRow(name="Alice", operation="邀请", invitable=True)) is False


async def test_find_row_without_a_handler_is_none():
    assert await SeatInviteDriver(None).find_row("Alice") is None
