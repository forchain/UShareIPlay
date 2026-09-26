"""座位相关测试共用的替身，刻意做成与生产协作者同形（见 PR #339 review C1/C2）。

- desk 是真正的 ElementWrapper —— 事件轮询就是这样从 page_source 构造的；
- 展开重扫路径用 raw WebElement 形状（find_element/find_elements）的桩；
- controller 的独占接口是 ui_session 异步上下文管理器，与 AppController 一致。
元素选择器取自真实 config.yaml，避免测试用一套自造 key 掩盖生产分歧。
"""

import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml
from lxml import etree

from ushareiplay.core.element_wrapper import ElementWrapper

DESK_RESOURCE_ID = "cn.soulapp.android:id/userRoot"
SOUL_PACKAGE = "cn.soulapp.android:id"


@lru_cache(maxsize=1)
def soul_elements() -> dict:
    """真实 config.yaml 的 soul.elements：元素 key -> resource-id。"""
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)["soul"]["elements"]


def _seat_xml(side: str, label: str, occupied: bool, default_name: str = "") -> str:
    """一个麦位。

    占用时 leftClState 存在（沿用 seating.py 的占用判据），label 是昵称；
    空位没有 state 节点，label 是座位号（房间里只有空位显示编号）或有 leftTvDefaultName（点击入座）。
    """
    nodes = []
    if default_name:
        nodes.append(f'<node resource-id="{SOUL_PACKAGE}/{side}TvDefaultName" text="{default_name}"/>')
    if label:
        nodes.append(f'<node resource-id="{SOUL_PACKAGE}/{side}TvLabelH" text="{label}"/>')
    inner = "".join(nodes)
    if occupied:
        inner = f'<node resource-id="{SOUL_PACKAGE}/{side}ClState">{inner}</node>'
    return f'<node resource-id="{SOUL_PACKAGE}/{side}UserView">{inner}</node>'


def build_desk_xml(
    left="",
    right="",
    y=100,
    left_occupied=False,
    right_occupied=False,
    left_default_name="",
    right_default_name="",
    bounds=None,
) -> str:
    bounds_attr = bounds if bounds else f"[40,{y}][400,{y + 160}]"
    return (
        f'<node resource-id="{DESK_RESOURCE_ID}" bounds="{bounds_attr}">'
        + _seat_xml("left", left, left_occupied, left_default_name)
        + _seat_xml("right", right, right_occupied, right_default_name)
        + "</node>"
    )


def build_desk_wrapper(handler, **kwargs) -> ElementWrapper:
    """按 EventManager 的方式把 desk 包成 ElementWrapper。"""
    root = etree.fromstring(f"<hierarchy>{build_desk_xml(**kwargs)}</hierarchy>".encode())
    desk_xml = root.xpath(f"//*[@resource-id='{DESK_RESOURCE_ID}']")[0]
    return ElementWrapper(desk_xml, handler, "seat_desk")


class FakeElementFinder:
    """与 ElementFinder 同形的 raw WebElement 路径。

    find_child_element 走 parent.find_element(...)，缺子元素时由 parent 抛错，
    与生产实现（ElementFinder.find_child_element -> parent.find_element）一致。
    """

    def __init__(self, elements, desks=None, popup_name=None):
        self.elements = elements
        self.desks = desks or []
        self.popup_name = popup_name
        self.wait_calls = 0
        self.on_wait = None

    def find_child_element(self, parent, element_key, log_failure=True):
        try:
            return parent.find_element(None, self.elements[element_key])
        except Exception:
            return None

    def find_elements(self, element_key):
        return list(self.desks)

    def wait_for_any_element(self, element_keys, timeout=10):
        self.wait_calls += 1
        if self.on_wait:
            self.on_wait()
        if not self.popup_name:
            return (None, None)
        return ("souler_name", SimpleNamespace(text=self.popup_name))


class RawSeatDesk:
    """raw WebElement 形状（展开重扫时 element_finder.find_elements 的返回物）。"""

    def __init__(self, children, location=None):
        self.children = children
        self.location = location or {"x": 40, "y": 100}
        self.size = {"width": 360, "height": 160}

    def find_element(self, _by, value):
        child = self.children.get(value)
        if child is None:
            raise KeyError(value)
        return child


class ClickableNode:
    """可点击叶子节点（raw WebElement 的 click() 契约）。"""

    def __init__(self, text=""):
        self.text = text
        self.clicked = False

    def click(self):
        self.clicked = True


class FakeController:
    """与 AppController 同形的独占接口：ui_session 异步上下文管理器。"""

    def __init__(self):
        self.ui_lock = asyncio.Lock()
        self.logger = MagicMock()
        self.sessions = []

    @asynccontextmanager
    async def ui_session(self, reason=""):
        async with self.ui_lock:
            self.sessions.append(reason)
            yield


class FakeSeatUI:
    """SeatUIManager 的展开/收起契约。"""

    def __init__(self, desks=None):
        self.desks = desks
        self.collapsed = False
        self.scrolled_rows = []

    async def expand_and_find_desks(self):
        return self.desks

    async def collapse_seats(self):
        self.collapsed = True
        return True

    def scroll_to_row(self, desk_index, seat_desks=None, duration=100):
        if not hasattr(self, "scrolled_rows"):
            self.scrolled_rows = []
        self.scrolled_rows.append(desk_index // 2)


def make_handler(elements=None, desks=None, popup_name=None, controller=None):
    handler = MagicMock()
    handler.logger = MagicMock()
    # 生产上传给 handler 的就是 config.yaml 的 soul 段
    handler.config = {"elements": elements or soul_elements()}
    handler.key_actions = MagicMock()
    handler.gesture_handler = MagicMock()
    handler.controller = controller
    handler.element_finder = FakeElementFinder(
        elements or soul_elements(), desks=desks, popup_name=popup_name
    )
    return handler
