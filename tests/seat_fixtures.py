"""座位相关测试共用的替身，刻意做成与生产协作者同形（见 PR #339 review C1/C2）。

- desk 是真正的 ElementWrapper —— 事件轮询就是这样从 page_source 构造的；
- 展开重扫路径用 raw WebElement 形状（find_element/find_elements）的桩；
- controller 的独占接口是 ui_session 异步上下文管理器，与 AppController 一致。
元素选择器取自真实 config.yaml，避免测试用一套自造 key 掩盖生产分歧。
"""

import asyncio
import re
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import yaml
from lxml import etree

from ushareiplay.core.element_wrapper import ElementWrapper

DESK_RESOURCE_ID = "cn.soulapp.android:id/userRoot"
SOUL_PACKAGE = "cn.soulapp.android:id"
# 只渲染底座的残片（见 #341）：没有 left/rightUserView，只有背景与底座。
BASE_ROOT_RESOURCE_ID = "cn.soulapp.android:id/bgRoot"
BOTTOM_VIEW_RESOURCE_IDS = (
    "cn.soulapp.android:id/leftBottomView",
    "cn.soulapp.android:id/rightBottomView",
)


@lru_cache(maxsize=1)
def soul_elements() -> dict:
    """真实 config.yaml 的 soul.elements：元素 key -> resource-id。"""
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)["soul"]["elements"]


def _seat_xml(
    side: str,
    label: str,
    occupied: bool,
    default_name: str = "",
    *,
    avatar_images: int = 0,
    state_widgets: bool = False,
) -> str:
    """一个麦位。

    占用时 leftClState 存在（沿用 seating.py 的占用判据），label 是昵称；
    空位没有 state 节点，label 是座位号（房间里只有空位显示编号）或有 leftTvDefaultName（点击入座）。

    `avatar_images` / `state_widgets` 描述纯 DOM 的占用与空座证据（见 #341）：
    AvatarView 下的 ImageView 数量（空座占位图恰好一张，占座是头像+挂件）与
    ClState 里的活跃控件（勋章、专注时长）。
    """
    avatar = ""
    if avatar_images:
        images = "".join('<node class="android.widget.ImageView"/>' for _ in range(avatar_images))
        avatar = f'<node resource-id="{SOUL_PACKAGE}/{side}AvatarView">{images}</node>'

    nodes = []
    if default_name:
        nodes.append(f'<node resource-id="{SOUL_PACKAGE}/{side}TvDefaultName" text="{default_name}"/>')
    if label:
        nodes.append(f'<node resource-id="{SOUL_PACKAGE}/{side}TvLabelH" text="{label}"/>')
    if state_widgets:
        nodes.append(f'<node resource-id="{SOUL_PACKAGE}/{side}IvMedal"/>')
        nodes.append(f'<node resource-id="{SOUL_PACKAGE}/{side}TvTime" text="28分钟"/>')
    inner = "".join(nodes)
    if occupied or state_widgets:
        inner = f'<node resource-id="{SOUL_PACKAGE}/{side}ClState">{inner}</node>'
    return f'<node resource-id="{SOUL_PACKAGE}/{side}UserView">{avatar}{inner}</node>'


def build_desk_xml(
    left="",
    right="",
    y=100,
    left_occupied=False,
    right_occupied=False,
    left_default_name="",
    right_default_name="",
    bounds=None,
    left_avatar_images=0,
    right_avatar_images=0,
    left_state_widgets=False,
    right_state_widgets=False,
) -> str:
    bounds_attr = bounds if bounds else f"[40,{y}][400,{y + 160}]"
    return (
        f'<node resource-id="{DESK_RESOURCE_ID}" bounds="{bounds_attr}">'
        + _seat_xml(
            "left",
            left,
            left_occupied,
            left_default_name,
            avatar_images=left_avatar_images,
            state_widgets=left_state_widgets,
        )
        + _seat_xml(
            "right",
            right,
            right_occupied,
            right_default_name,
            avatar_images=right_avatar_images,
            state_widgets=right_state_widgets,
        )
        + "</node>"
    )


def build_desk_wrapper(handler, **kwargs) -> ElementWrapper:
    """按 EventManager 的方式把 desk 包成 ElementWrapper。"""
    root = etree.fromstring(f"<hierarchy>{build_desk_xml(**kwargs)}</hierarchy>".encode())
    desk_xml = root.xpath(f"//*[@resource-id='{DESK_RESOURCE_ID}']")[0]
    return ElementWrapper(desk_xml, handler, "seat_desk")


SEAT_DOM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "seat_dom"


def load_real_desk_nodes(fixture_name: str) -> list:
    """真机 page_source dump 里的 userRoot 桌位子树（Appium 原始节点，含重复节点怪癖）。

    夹具由设备实测 dump 裁剪而来（tests/fixtures/seat_dom/）—— 座位号 label、
    裁切高度、AvatarView 子节点数都是真机事实，不是构造出来的假设。
    """
    root = etree.parse(str(SEAT_DOM_FIXTURES / fixture_name)).getroot()
    return root.findall(f".//*[@resource-id='{DESK_RESOURCE_ID}']")


def build_real_desk_wrappers(handler, fixture_name: str) -> list:
    """真机 dump -> 事件轮询形状的 ElementWrapper 列表。"""
    return [ElementWrapper(node, handler, "seat_desk") for node in load_real_desk_nodes(fixture_name)]


def _location_from_bounds(bounds_str: str) -> tuple[dict, dict]:
    numbers = [int(n) for n in re.findall(r"-?\d+", bounds_str or "")]
    if len(numbers) != 4:
        return {"x": 0, "y": 0}, {"width": 0, "height": 0}
    x1, y1, x2, y2 = numbers
    return {"x": x1, "y": y1}, {"width": x2 - x1, "height": y2 - y1}


class RawDumpNode:
    """真机 dump 节点的 raw WebElement 形状。

    必须包一层：lxml 的叶子节点是 falsy 的（`if elem` 直接判空），而 Appium 的
    WebElement 恒为真 —— 直接喂 lxml 节点会把生产代码里的 `if elem` 判断骗过去。
    """

    def __init__(self, xml_node):
        self._node = xml_node
        self.text = xml_node.get("text") or ""
        self.clicked = False

    def click(self):
        self.clicked = True


def build_real_raw_desks(fixture_name: str) -> list:
    """同一份真机 DOM 的 raw WebElement 形状（展开重扫路径的 find_elements 返回物）。

    子节点按 resource-id 建索引，与 Appium 的 parent.find_element 一样返回文档序第一个；
    头像子树不在 raw 路径里数图（生产契约见 seat_observation._avatar_image_count）。
    """
    desks = []
    for node in load_real_desk_nodes(fixture_name):
        children: dict = {}
        for child in node.iterdescendants():
            rid = child.get("resource-id")
            if rid and rid not in children:
                children[rid] = RawDumpNode(child)
        location, size = _location_from_bounds(node.get("bounds"))
        desk = RawSeatDesk(children, location=location)
        desk.size = size
        desks.append(desk)
    return desks


def build_base_fragment_xml(y=100, bounds=None) -> str:
    """只渲染底座的残片：bgRoot + left/rightBottomView，没有任何 userView。"""
    bounds_attr = bounds if bounds else f"[40,{y}][400,{y + 18}]"
    bottoms = "".join(f'<node resource-id="{rid}"/>' for rid in BOTTOM_VIEW_RESOURCE_IDS)
    return (
        f'<node resource-id="{DESK_RESOURCE_ID}" bounds="{bounds_attr}">'
        f'<node resource-id="{BASE_ROOT_RESOURCE_ID}"/>'
        f"{bottoms}"
        "</node>"
    )


def build_base_fragment_wrapper(handler, **kwargs) -> ElementWrapper:
    """按 EventManager 的方式把底座残片包成 ElementWrapper。"""
    root = etree.fromstring(f"<hierarchy>{build_base_fragment_xml(**kwargs)}</hierarchy>".encode())
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
        # 弹窗（头像名片）是否在屏幕上：与生产一致 —— 关掉后节点不在 dump 里，
        # 与「昵称读不读得出来」是两件事（卡片刚渲染出来时 wait 可能已经超时）。
        self.popup_open = popup_name is not None
        self.wait_calls = 0
        self.on_wait = None

    def find_child_element(self, parent, element_key, log_failure=True):
        try:
            return parent.find_element(None, self.elements[element_key])
        except Exception:
            return None

    def find_elements(self, element_key):
        return list(self.desks)

    def try_find_element(self, element_key, log=False, clickable=False):
        if self.popup_open and element_key in ("souler_name", "user_name"):
            return SimpleNamespace(text=self.popup_name or "")
        return None

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
    """座位面板协作者的展开/收起契约（`SeatSubsystem.panel` 的注入替身）。"""

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


def build_live_desk_wrapper(handler, left, right, y=600, bounds=None) -> ElementWrapper:
    """真机麦位 DOM 形状的桌位（事件轮询的 ElementWrapper）。

    左右两侧各是一个三元组 ``(座位号, 是否占座, 身份文字或 None)``，渲染规则取自
    真机 dump（tests/fixtures/seat_dom/expanded_*_with_anchor.xml）：

    - **空位**：只有 ``TvDefaultName``「点击入座」+ 一张占位图，没有 ClState，
      也**没有 label 节点**；
    - **占座**：``ClState`` + ``IvMedal`` + ``TvTime`` + 4 张图，``TvLabelH`` 是
      **麦位编号**（普通用户）或身份文字（群主/管理）。

    关键事实：普通用户的**昵称不在麦位 DOM 里**，只能点头像读弹窗
    （``inspect_occupant``）。用 ``left="张三", left_occupied=True`` 那种
    「label 就是昵称」的形状测不出真机换座——它跳过了昵称缺失这条主路径。
    """
    kwargs = {"y": y, "bounds": bounds}
    for side, (seat_number, seated, role) in (("left", left), ("right", right)):
        if seated:
            kwargs[f"{side}_occupied"] = True
            kwargs[f"{side}_state_widgets"] = True
            kwargs[f"{side}_avatar_images"] = 4
            kwargs[side] = role or str(seat_number)
        else:
            kwargs[f"{side}_default_name"] = "点击入座"
            kwargs[f"{side}_avatar_images"] = 1
    return build_desk_wrapper(handler, **kwargs)


def build_live_raw_desk(left, right, y=600) -> RawSeatDesk:
    """真机麦位 DOM 形状的桌位（展开重扫路径的 raw WebElement）。

    与 build_live_desk_wrapper 同一套三元组语义；raw 路径数不到 AvatarView 里的
    图片（Appium XPath 是整页作用域），占用证据只有 ClState 与 label。
    """
    elements = soul_elements()
    children = {}
    for side, (seat_number, seated, role) in (("left", left), ("right", right)):
        label = (role or str(seat_number)) if seated else ""
        children[elements[f"{side}_label"]] = SimpleNamespace(text=label)
        if seated:
            children[elements[f"{side}_state"]] = SimpleNamespace(text="")
        else:
            children[elements[f"{side}_default_name"]] = SimpleNamespace(text="点击入座")
    return RawSeatDesk(children, location={"x": 40, "y": y})


# ---------------------------------------------------------------------------
# 真机形状的整屏 page_source 生成器：视口相位 × 占用情况 × 换座残留渲染
#
# 几何取自 tests/fixtures/seat_dom/ 的真机 dump：两列三排共 6 张桌位，
# 一张桌位左右各一个麦位，奇数号在左、偶数号在右。
# ---------------------------------------------------------------------------

LIVE_DESK_ORIGIN = (28, 566)
LIVE_DESK_SIZE = (309, 207)
LIVE_DESK_GAP = (46, 27)
LIVE_SIDE_INSET = {"left": (32, 52), "right": (142, 55)}
LIVE_SIDE_SIZE = (135, 167)
# 视口相位 -> (完整渲染的 desk 序号, 只露出残片的 desk 序号)
LIVE_VIEWPORT_PHASES = {
    "top": ((0, 1, 2, 3), (4, 5)),
    "bottom": ((2, 3, 4, 5), (0, 1)),
    "collapsed_top": ((0, 1), (2, 3)),
    "collapsed_bottom": ((4, 5), (2, 3)),
    # 展开重扫合并顶/底两次读数后的等效全景（两次 find_elements 都看得见全部桌位）
    "full": ((0, 1, 2, 3, 4, 5), ()),
}


def _bounds_str(x1, y1, x2, y2) -> str:
    return f"[{x1},{y1}][{x2},{y2}]"


def live_desk_bounds(desk_index: int) -> tuple[int, int, int, int]:
    ox, oy = LIVE_DESK_ORIGIN
    w, h = LIVE_DESK_SIZE
    gx, gy = LIVE_DESK_GAP
    col, row = desk_index % 2, desk_index // 2
    x1 = ox + col * (w + gx)
    y1 = oy + row * (h + gy)
    return x1, y1, x1 + w, y1 + h


def live_seat_bounds(seat_number: int) -> dict:
    """麦位 UserView 的屏幕坐标（:seat 2 <n> 的点击落点就应该是它）。"""
    desk_index = (seat_number - 1) // 2
    side = "left" if seat_number % 2 else "right"
    x1, y1, _x2, _y2 = live_desk_bounds(desk_index)
    dx, dy = LIVE_SIDE_INSET[side]
    w, h = LIVE_SIDE_SIZE
    return {"x": x1 + dx, "y": y1 + dy, "width": w, "height": h}


def _live_seat_xml(side: str, seat_number: int, occupant) -> str:
    """一个麦位。occupant：``True`` 普通用户占座 / 字符串 = 身份文字 / 其它 = 空座。

    占用与否的 DOM 证据与真机 dump 一致：空座只有 1 张占位图 + TvDefaultName
    「点击入座」，占座是 4 张图 + ClState（内含 BgUserStateH 与 TvLabelH）+
    IvMedal + TvTime。
    """
    b = live_seat_bounds(seat_number)
    bounds = _bounds_str(b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"])
    user_view = f'<node resource-id="{SOUL_PACKAGE}/{side}UserView" bounds="{bounds}">'
    seated = bool(occupant)
    images = '<node class="android.widget.ImageView"/>' * (1 if not seated else 4)
    avatar = (
        f'<node resource-id="{SOUL_PACKAGE}/{side}AvatarView" '
        f'bounds="{_bounds_str(b["x"], b["y"], b["x"] + 108, b["y"] + 108)}">{images}</node>'
    )
    if not seated:
        # 空座：没有 ClState，也没有 label 节点（房间里只有占座麦位渲染 TvLabelH）
        return (
            f"{user_view}{avatar}"
            f'<node resource-id="{SOUL_PACKAGE}/{side}TvDefaultName" text="点击入座"/></node>'
        )
    state = (
        f'<node resource-id="{SOUL_PACKAGE}/{side}ClState">'
        f'<node resource-id="{SOUL_PACKAGE}/{side}BgUserStateH"/>'
        f'<node resource-id="{SOUL_PACKAGE}/{side}TvLabelH" '
        f'text="{seat_number if occupant is True else occupant}"/></node>'
    )
    medal = (
        f'<node resource-id="{SOUL_PACKAGE}/{side}IvMedal"/>'
        f'<node resource-id="{SOUL_PACKAGE}/{side}TvTime" text="2分钟"/>'
    )
    return f"{user_view}{avatar}{state}{medal}</node>"


def build_live_page_source(occupants: dict, phase: str = "top") -> str:
    """按视口相位拼一份真机形状的 page_source。

    Args:
        occupants: ``{座位号: 占用者}``。``True`` = 普通用户占座（TvLabelH 渲染成
            麦位编号，**昵称不在 DOM 里**，只能点头像弹窗读）；``"群主"``/``"管理"``
            = 身份文字；省略 = 空座。
        phase: top / bottom / collapsed_top / collapsed_bottom，决定哪些桌位完整
            渲染、哪些只露出残片（残片没有 userView，读不出任何麦位数据）。
    """
    full, fragments = LIVE_VIEWPORT_PHASES[phase]
    desks = []
    for desk_index in range(6):
        x1, y1, x2, y2 = live_desk_bounds(desk_index)
        if desk_index not in full:
            if desk_index not in fragments:
                continue
            # 残片：只剩背景与底座，与真机滑出视口的桌位同形
            desks.append(
                f'<node resource-id="{DESK_RESOURCE_ID}" bounds="{_bounds_str(x1, y1, x2, y1 + 18)}">'
                f'<node resource-id="cn.soulapp.android:id/bgRoot"/>'
                f'<node resource-id="cn.soulapp.android:id/leftBottomView"/>'
                f'<node resource-id="cn.soulapp.android:id/rightBottomView"/></node>'
            )
            continue
        sides = []
        for side, offset in (("left", 1), ("right", 2)):
            seat_number = desk_index * 2 + offset
            sides.append(_live_seat_xml(side, seat_number, occupants.get(seat_number)))
        desks.append(
            f'<node resource-id="{DESK_RESOURCE_ID}" bounds="{_bounds_str(x1, y1, x2, y2)}">'
            f'<node resource-id="cn.soulapp.android:id/bgRoot"/>'
            f"{''.join(sides)}</node>"
        )
    return "<hierarchy>" + "".join(desks) + "</hierarchy>"


def build_live_desk_wrappers_for(handler, occupants: dict, phase: str = "top") -> list:
    """page_source -> 事件轮询形状的桌位列表（与 EventManager 的构造方式一致）。"""
    root = etree.fromstring(build_live_page_source(occupants, phase).encode("utf-8"))
    return [
        ElementWrapper(node, handler, "seat_desk")
        for node in root.xpath(f"//*[@resource-id='{DESK_RESOURCE_ID}']")
    ]


def build_live_raw_desks_for(occupants: dict, phase: str = "top") -> list:
    """page_source -> 展开重扫路径的 raw WebElement 桌位列表。"""
    root = etree.fromstring(build_live_page_source(occupants, phase).encode("utf-8"))
    desks = []
    for node in root.xpath(f"//*[@resource-id='{DESK_RESOURCE_ID}']"):
        children: dict = {}
        for child in node.iterdescendants():
            rid = child.get("resource-id")
            if rid and rid not in children:
                children[rid] = RawDumpNode(child)
        location, size = _location_from_bounds(node.get("bounds"))
        desk = RawSeatDesk(children, location=location)
        desk.size = size
        desks.append(desk)
    return desks
