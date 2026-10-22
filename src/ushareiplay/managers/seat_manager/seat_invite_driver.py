"""「邀请入座」底部弹窗的 UI 驱动：弹窗是否开着、翻页找人、点「邀请」、按 X 关窗。

派对房间里点一个**空座位**会弹出「邀请入座」底部弹窗：它列出房间里的在线用户，
每人一行，行尾一个操作按钮（`tvOperation`）写着「邀请」/「上座」（可点）或
「已上座」（人已经在座上，点不动）。本模块只管这个弹窗，座位面板本身的展开/收起/
整排滚动交给 `SeatPanelDriver`。

它刻意是**普通可注入对象**，不是单例：没有全局状态，handler 由构造注入，所以
单元测试可以整段替换掉设备依赖 —— 与 `SeatPanelDriver` 同一原则。

## 为什么这个弹窗值得单独一个模块

「邀请」这件事没法靠点坐标完成：房间里在线的人可能几十个，弹窗里的列表是分页的，
目标用户可能在第二页、第三页，甚至压根不在房间里（已离房）。所以这里把
「读当前页 → 逐页比对可见昵称 → 翻页」这件事收成一处，调用方只表达意图：
「把这个人请到那个座位上」。

## 按返回的铁律

派对房间里一次盲按返回键就是退出派对房间 —— 真机上房主换座后的残留渲染被读成
「占座但身份未知」，点名没点出任何弹窗就按了 back，房间界面就此消失（真机
09-28 18:07/20:46）。**本模块一次 press_back 都不按**：关这个弹窗只认界面右上角
那个 X 按钮（`ivClose`）。读不到 X 就把弹窗留在那里，也比拿整个房间去赌强。

## 名字的铁律

弹窗行里的昵称是 Soul UI 上的**可见昵称**（分身名），而 DB 里存的是 canonical 名
（主账号名），两者字符串不同。所以本模块只做「可见昵称 == 可见昵称」这一个命名域
里的比较；调用方必须先把名字解析成房间里当前可见的那个名字
（`InfoManager.resolve_visible_username`）再传进来。

## 元素选择器

全部选择器集中在 `config.yaml` 的 `soul.elements`（`seat_invite_*`），本模块不持有
任何硬编码的 resource-id 或 XPath。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SeatInviteRow:
    """「邀请入座」弹窗里的一行。

    Attributes:
        name: 行内昵称（UI 可见名）。
        operation: 操作按钮文案：'邀请' / '已上座' / '上座' / ''。
        invitable: operation 属于可邀请文案。
        element: 行元素（raw WebElement）。
        operation_element: 行内操作按钮元素；点「邀请」点的是它，不是整行。
    """

    name: str
    operation: str
    invitable: bool
    element: Any = None
    operation_element: Any = field(default=None)


class SeatInviteDriver:
    """「邀请入座」底部弹窗的 UI 驱动。

    Args:
        handler: SoulHandler。提供 element_finder / gesture_handler / key_actions。
    """

    ROW_KEY = "seat_invite_row"
    NAME_KEY = "seat_invite_name"
    OPERATION_KEY = "seat_invite_operation"
    CLOSE_KEY = "seat_invite_close"
    PANEL_KEY = "seat_invite_panel"

    # 可点「邀请」的按钮文案。「上座」与「邀请」是同一个意思的两种措辞。
    # 这是**界面文案**而不是元素选择器，所以住在 Python 侧（与 SeatPanelDriver 的
    # EXPAND_LABEL = "展开" 同一处理）：选择器一律在 config.yaml，文案不是。
    INVITABLE_LABELS = ("邀请", "上座")
    # 「已上座」＝人已经在座位上，再点也没有意义。
    SEATED_LABELS = ("已上座",)

    # 翻页滑动的时长（毫秒）。
    SWIPE_DURATION_MS = 400
    # 翻页后等下一页渲染出来的时间。
    SWIPE_SETTLE_SECONDS = 0.5
    # 等弹窗渲染出来的轮询间隔。
    OPEN_POLL_SECONDS = 0.1
    # 读不到窗口尺寸时的兜底屏幕尺寸（只用来估算滑动区域）。
    FALLBACK_SCREEN_WIDTH = 1080
    FALLBACK_SCREEN_HEIGHT = 1920

    def __init__(self, handler=None):
        self.handler = handler

    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, value):
        # logger 不在构造期快照：座位子系统换手时 handler 可能被换掉，快照会让驱动
        # 一直往旧 handler 的 logger 上写（与 SeatPanelDriver 同一处理）。
        self._handler = value
        self._logger = getattr(value, "logger", None)

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self.handler, "logger", None) or logging.getLogger(
                "seat_invite_driver"
            )
        return self._logger

    # ------------------------------------------------------------------
    # 基础读取
    # ------------------------------------------------------------------

    @property
    def _finder(self):
        return getattr(self.handler, "element_finder", None) if self.handler else None

    def _child_text(self, row, element_key: str) -> str:
        """行内某个子节点的文本；读不到就是空串。"""
        finder = self._finder
        if finder is None or row is None:
            return ""
        try:
            element = finder.find_child_element(row, element_key, log_failure=False)
        except TypeError:
            # 替身/旧实现可能没有 log_failure 形参
            try:
                element = finder.find_child_element(row, element_key)
            except Exception:
                return ""
        except Exception:
            return ""
        if element is None:
            return ""
        return (getattr(element, "text", "") or "").strip()

    def _child_element(self, row, element_key: str):
        """行内某个子节点元素；读不到就是 None。"""
        finder = self._finder
        if finder is None or row is None:
            return None
        try:
            return finder.find_child_element(row, element_key, log_failure=False)
        except TypeError:
            try:
                return finder.find_child_element(row, element_key)
            except Exception:
                return None
        except Exception:
            return None

    @classmethod
    def _is_invitable(cls, operation: str) -> bool:
        """操作按钮文案是不是「可以点邀请」。

        「已上座」必须先排除：它**含有**「上座」两个字，直接按「上座」认会把一个
        已经在座上的人当成可邀请的。
        """
        if any(label in operation for label in cls.SEATED_LABELS):
            return False
        return any(label in operation for label in cls.INVITABLE_LABELS)

    def _read_raw_rows(self) -> list:
        """当前可见的邀请行**元素**（原始行，读不出昵称的行也在里面）。

        行查找优先收敛到弹窗自己的列表容器（`seat_invite_panel`）：全屏搜
        `userContainer` 会把别的浮层里的同名节点一起捞进来。容器选择器是尽力而为
        的结构化 XPath，读不到容器时退回全屏查找。

        Returns:
            原始行元素列表；弹窗不在页面上时是空列表。
        """
        finder = self._finder
        if finder is None:
            return []

        panel = self._panel_element()
        if panel is not None:
            find_child = getattr(finder, "find_child_elements", None)
            if find_child is not None:
                try:
                    return list(find_child(panel, self.ROW_KEY) or [])
                except Exception as e:
                    self.logger.debug(f"在弹窗列表容器里查找用户行失败: {e}")

        try:
            return list(finder.find_elements(self.ROW_KEY) or [])
        except Exception as e:
            # 读失败是可恢复的读数问题：按日志铁律降到 DEBUG（轮询里每 100ms
            # 就会读一次，WARNING 会刷屏）。
            self.logger.debug(f"读取邀请入座弹窗的用户行失败: {e}")
            return []

    def _build_rows(self, raw_rows) -> list:
        """把原始行变成 `SeatInviteRow`。

        读不出昵称的行**也留着**（name 为空串）：调用方要能区分「这一页还没渲染
        完」和「弹窗已经不在了」，整行丢掉就把两者混成一件事。
        """
        rows = []
        for row in raw_rows or []:
            name = self._child_text(row, self.NAME_KEY)
            operation_element = self._child_element(row, self.OPERATION_KEY)
            operation = (getattr(operation_element, "text", "") or "").strip()
            rows.append(
                SeatInviteRow(
                    name=name,
                    operation=operation,
                    invitable=self._is_invitable(operation),
                    element=row,
                    operation_element=operation_element,
                )
            )
        return rows

    def read_rows(self) -> list:
        """读当前可见的邀请行。

        读不出昵称的行整行跳过：比对用的是可见昵称，没有昵称的行没有意义
        （也可能只是这一行还没渲染完，翻页时还会再读一次）。
        """
        return [row for row in self._build_rows(self._read_raw_rows()) if row.name]

    def is_open(self) -> bool:
        """弹窗是否开着。

        证据两条：**读得到至少一行邀请行**，或**弹窗自己的列表容器在页面上**。
        两者都读不到才算没开。不依赖弹窗标题 —— 标题文案随版本变，而行与容器
        都是弹窗自己渲染的，它们在就说明弹窗在。
        """
        if self.handler is None:
            return False
        try:
            if self.read_rows():
                return True
            return self._panel_element() is not None
        except Exception as e:
            self.logger.debug(f"判定邀请入座弹窗是否打开失败: {e}")
            return False

    def _sheet_on_screen(self) -> bool:
        """还有证据表明「邀请入座」弹窗在屏幕上吗。

        证据：读得到邀请行，或弹窗自己的列表容器还在页面上。
        """
        try:
            if self.read_rows():
                return True
        except Exception:
            pass
        return self._panel_element() is not None

    async def wait_until_open(self, timeout: float = 3.0) -> bool:
        """等弹窗渲染出来。

        超时不代表没开，只代表没在这个窗口里读到 —— 调用方要按「没打开」处理，
        但绝不能因此去按返回键。

        轮询期间每一次读不到都只是「还没渲染出来」，按日志铁律不刷 WARNING；
        「弹窗始终没开」这个**结果**由调用方记一笔（见 `invite_user_to_seat`）。
        """
        deadline = time.monotonic() + timeout
        while True:
            if self.is_open():
                return True
            if time.monotonic() >= deadline:
                self.logger.debug("等待「邀请入座」弹窗打开超时")
                return False
            await asyncio.sleep(self.OPEN_POLL_SECONDS)

    # ------------------------------------------------------------------
    # 翻页
    # ------------------------------------------------------------------

    def _panel_element(self):
        """弹窗的列表容器元素；读不到就是 None。

        容器既是行查找的收敛范围（见 `_read_raw_rows`），也是「弹窗还在屏幕上」的
        证据之一（见 `is_open`）。
        """
        finder = self._finder
        if finder is None:
            return None
        try:
            return finder.try_find_element(self.PANEL_KEY, log=False)
        except Exception:
            return None

    def _panel_bounds(self) -> Optional[dict]:
        """弹窗列表容器的屏幕坐标；读不到就是 None。"""
        panel = self._panel_element()
        if not panel:
            return None

        for attr in ("rect", "bounds"):
            value = getattr(panel, attr, None)
            if isinstance(value, dict) and value.get("width") and value.get("height"):
                return value

        location = getattr(panel, "location", None)
        size = getattr(panel, "size", None)
        if isinstance(location, dict) and isinstance(size, dict):
            return {
                "x": location.get("x", 0),
                "y": location.get("y", 0),
                "width": size.get("width", 0),
                "height": size.get("height", 0),
            }
        return None

    def _screen_size(self) -> tuple:
        """屏幕尺寸；读不到就用兜底常量。"""
        driver = getattr(self.handler, "driver", None) if self.handler else None
        if driver is not None:
            try:
                window = driver.get_window_size()
                width = int(window.get("width", 0))
                height = int(window.get("height", 0))
                if width > 0 and height > 0:
                    return width, height
            except Exception:
                pass
        return self.FALLBACK_SCREEN_WIDTH, self.FALLBACK_SCREEN_HEIGHT

    def _swipe_area(self) -> tuple:
        """滑动区域（start_x, start_y, end_x, end_y）。

        优先用弹窗列表容器自己的坐标 —— 弹窗是底部抽屉，滑动必须落在列表里，
        滑到房间界面上就是误触。读不到容器坐标时退回屏幕中央偏下的一片区域
        （底部抽屉就出现在那一带）。
        """
        bounds = self._panel_bounds()
        if bounds:
            x = bounds.get("x", 0) + bounds.get("width", 0) // 2
            height = bounds.get("height", 0)
            start_y = bounds.get("y", 0) + int(height * 0.75)
            end_y = bounds.get("y", 0) + int(height * 0.25)
            return x, start_y, x, end_y

        width, height = self._screen_size()
        x = width // 2
        return x, int(height * 0.75), x, int(height * 0.45)

    async def _scroll_list(self) -> bool:
        """把邀请列表往下翻一页（内容上移 = 看到后面的人）。"""
        gesture = getattr(self.handler, "gesture_handler", None) if self.handler else None
        if gesture is None or not hasattr(gesture, "swipe"):
            return False

        start_x, start_y, end_x, end_y = self._swipe_area()
        try:
            gesture.swipe(start_x, start_y, end_x, end_y, self.SWIPE_DURATION_MS)
        except Exception as e:
            self.logger.warning(f"滑动邀请入座弹窗的用户列表失败: {e}")
            return False

        # 滑动之后要给列表一点渲染时间，否则读到的是滑动途中的画面
        await asyncio.sleep(self.SWIPE_SETTLE_SECONDS)
        return True

    async def find_row(self, visible_name: str, max_pages: int = 10) -> Optional[SeatInviteRow]:
        """在邀请列表里找某个**可见昵称**。

        只在「可见昵称」这一个命名域里比对 —— 弹窗里渲染的就是分身名，调用方必须
        已经把名字解析成房间里当前可见的那个名字（`InfoManager.resolve_visible_username`）。

        翻页终止条件：找到了 / 当前页的行签名与上一页重复（没有更多数据了）/
        翻满 `max_pages` 页 / 弹窗已经不在了。

        「一页原始行都读不到」= 弹窗不在了；「读得到行、却一个昵称都读不出来」=
        这一页还没渲染完 —— 那是**半渲染**，翻页继续找，不能当成「人不在列表里」。

        Returns:
            命中的那一行；找不到就是 None。
        """
        if self.handler is None:
            return None

        seen_signatures = set()
        pages = max(1, max_pages)
        for page in range(pages):
            raw_rows = self._read_raw_rows()
            if not raw_rows:
                # 一行原始行都读不到：弹窗已经不在了。
                return None

            rows = self._build_rows(raw_rows)
            for row in rows:
                if row.name == visible_name:
                    return row

            # 页签名：昵称读得出来就用昵称，读不出来退回操作文案（「邀请」/
            # 「已上座」）—— 半渲染的一页也得有个签名，否则翻页停不下来。
            signature = tuple((row.name or row.operation) for row in rows)
            if signature in seen_signatures:
                self.logger.debug("邀请入座列表翻页后内容未变化，停止翻页")
                return None
            seen_signatures.add(signature)

            if not any(row.name for row in rows):
                self.logger.debug("邀请入座列表这一页还没渲染出昵称，翻页继续找")

            if page == pages - 1:
                break

            if not await self._scroll_list():
                return None

        return None

    # ------------------------------------------------------------------
    # 点击与关窗
    # ------------------------------------------------------------------

    def click_invite(self, row: SeatInviteRow) -> bool:
        """点行内的「邀请」按钮。

        只有可邀请的行才点：给一个「已上座」的人再点一次邀请没有意义，点了也只
        会得到一个错。
        """
        if row is None or not row.invitable:
            return False

        element = getattr(row, "operation_element", None)
        if element is None:
            return False

        try:
            element.click()
        except Exception as e:
            self.logger.warning(f"点击邀请按钮失败: {e}")
            return False
        return True

    def close(self) -> bool:
        """点弹窗右上角的 X 关掉它。

        只在**还有证据表明弹窗在屏幕上**时才点：`ivClose` 是全 App 共用的
        resource-id，别的浮层（头像名片等）用的是同一个 X —— 弹窗不在的时候点它，
        关掉的是别人的浮层。

        **绝不按返回键**：派对房间里一次盲按 back 就是退出派对房间。读不到 X 就
        返回 False，让调用方知道「弹窗可能还在」，而不是拿房间去赌。
        """
        finder = self._finder
        if finder is None:
            return False

        if not self._sheet_on_screen():
            self.logger.debug("没有证据表明「邀请入座」弹窗在屏幕上，不点关闭按钮")
            return False

        try:
            button = finder.try_find_element(self.CLOSE_KEY, log=False)
        except Exception as e:
            self.logger.warning(f"查找邀请入座弹窗的关闭按钮失败: {e}")
            return False

        if not button:
            return False

        try:
            button.click()
        except Exception as e:
            self.logger.warning(f"点击邀请入座弹窗的关闭按钮失败: {e}")
            return False
        return True
