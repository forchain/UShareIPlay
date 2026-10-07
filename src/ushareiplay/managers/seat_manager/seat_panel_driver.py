"""座位面板的 UI 驱动：面板状态、展开/收起、整排滚动、麦位头像弹窗的安全生命周期。

原先这些动作散在三个单例里（`SeatUIManager` 管面板，`SeatObservationManager` 管
麦位弹窗，`SeatCheckManager` 又自己展开一次），每个调用点各自决定「要不要点展开
按钮」「读不到昵称时要不要按返回」。本模块把它们收成一处，调用方只表达意图。

它刻意是**普通可注入对象**，不是单例：没有全局状态，handler 与协作者都由构造注入，
所以单元测试可以整段替换掉设备依赖（`#400` 负责合并三个座位单例，`#401` 负责接线）。

## 按返回的铁律

派对房间里一次盲按返回键就是退出派对房间 —— 真机上房主换座后的残留渲染被读成
「占座但身份未知」，点名没点出任何弹窗就按了 back，房间界面就此消失（真机
09-28 18:07/20:46）。`RoomInfoWindow.ensure_closed` 记过同一笔账：优先走 UI 正规
关窗操作，只有在弹窗标志**依然在屏幕上**时才拿 press_back 兜底。

所以本模块里每一次 press_back 都由证据授权：读到弹窗自己渲染的昵称节点（或超时
后卡片仍在屏幕上）才说明弹窗真开着，而按下之前还要再取一次证 —— 读完之后卡片
可能已经被别的流程关掉，此刻拿不到证据就宁可留着，绝不拿房间去赌。
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from ushareiplay.core.element_wrapper import ElementWrapper

# 面板按钮文本：按钮上写的是「点我之后」的状态，不是当前状态。
EXPAND_LABEL = "展开"
COLLAPSE_LABEL = "收起"

# 麦位头像弹窗开着的证据：弹窗自己渲染的昵称节点（两种名片各一套 id）。
# 与 RoomInfoWindow.DIALOG_KEYS 同一套判法：节点在 dump 里才说明弹窗开着。
SEAT_CARD_EVIDENCE_KEYS = ("souler_name", "user_name")

EXPAND_SEATS_KEY = "expand_seats"
SEAT_DESK_KEY = "seat_desk"

# 面板展开/收起都有动画，读桌位与点麦位都得等它稳定下来。
PANEL_SETTLE_SECONDS = 0.5
# 展开后必须完整渲染出 6 张桌位（两列三排）才认为面板真的开了。
EXPECTED_DESK_COUNT = 6
# 点头像后等弹窗渲染出来的上限。超时不代表没开，只代表没在这个窗口里读到。
SEAT_CARD_TIMEOUT = 1.5
# 点头像后的渲染延迟，与 SeatObservationManager.inspect_occupant 一致。
SEAT_CARD_TAP_SETTLE_SECONDS = 0.3
# 关掉弹窗后的回场延迟。
SEAT_CARD_DISMISS_SETTLE_SECONDS = 0.2


@dataclass
class SeatCardView:
    """一次麦位头像点名的读数结果。

    Attributes:
        opened: 弹窗确实开着（读到昵称节点，或超时后卡片仍在屏幕上）。
        name: 读到的昵称；读不到时是 None（「身份未知」留给下一轮）。
        name_key: 命中的证据元素 key，便于排障时知道是哪套名片。
    """

    opened: bool = False
    name: Optional[str] = None
    name_key: Optional[str] = None


class SeatPanelDriver:
    """座位面板的 UI 驱动。

    Args:
        handler: SoulHandler。提供 element_finder / key_actions / gesture_handler。
    """

    EXPAND_LABEL = EXPAND_LABEL
    COLLAPSE_LABEL = COLLAPSE_LABEL
    SEAT_CARD_EVIDENCE_KEYS = SEAT_CARD_EVIDENCE_KEYS

    # config.yaml 里没有对应元素时兜底的选择器。点头像只需要这四个。
    _FALLBACK_SELECTORS = {
        "left_state": "cn.soulapp.android:id/leftClState",
        "right_state": "cn.soulapp.android:id/rightClState",
        "left_seat": "cn.soulapp.android:id/leftUserView",
        "right_seat": "cn.soulapp.android:id/rightUserView",
    }

    def __init__(self, handler=None):
        # 面板是否展开的缓存。按钮读不到时它是唯一可用的取值（见 is_expanded）。
        self.expanded = False
        self.handler = handler

    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, value):
        # logger 原来是在构造时快照的。座位子系统合并后 handler 可以被后换掉
        # （SeatObservationManager.bind_handler 会改写 seat_ui.handler），快照必须
        # 跟着走，否则驱动会一直往旧 handler 的 logger 上写。
        self._handler = value
        self._logger = getattr(value, "logger", None)

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self.handler, "logger", None) or logging.getLogger("seat_panel_driver")
        return self._logger

    # ------------------------------------------------------------------
    # 面板状态
    # ------------------------------------------------------------------

    def _expand_button(self):
        """座位面板的展开/收起按钮。"""
        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            return None
        return finder.try_find_element(EXPAND_SEATS_KEY, log=False)

    def is_expanded(self) -> bool:
        """读按钮文本判定面板当前是否展开，并刷新缓存。

        按钮写着的是「点我之后」的状态：写着「收起」说明现在开着。按钮读不到
        （被弹窗盖住、页面已切走）时无法判定，返回缓存值 —— 按钮不在页面上不代表
        面板变了，把它当成收起会让下一轮白点一次展开。
        """
        if self.handler is None:
            return False

        try:
            button = self._expand_button()
        except Exception as e:
            self.logger.warning(f"读取座位面板按钮失败，沿用缓存状态: {e}")
            return self.expanded

        if not button:
            self.logger.debug("座位面板按钮不在页面上，沿用缓存状态")
            return self.expanded

        text = getattr(button, "text", "") or ""
        if COLLAPSE_LABEL in text:
            self.expanded = True
        elif EXPAND_LABEL in text:
            self.expanded = False
        else:
            self.logger.warning(f"座位面板按钮文本 '{text}' 无法判断展开状态，沿用缓存状态")
        return self.expanded

    # ------------------------------------------------------------------
    # 展开 / 收起
    # ------------------------------------------------------------------

    def _toggle(self, target_text: str) -> bool:
        """点一次面板按钮，但只在按钮确实写着 target_text 时点。

        展开/收起共用同一个按钮，靠按钮文本区分：文本不是目标关键字说明面板已经
        在另一种状态（或文本认不出来），此时任何一次点击都不可预测 —— 展开按钮上
        多点一下就是点进了第一个麦位。
        """
        button = self._expand_button()
        if not button:
            self.logger.warning(f"未找到座位面板按钮，无法切到 '{target_text}' 状态")
            return False

        text = getattr(button, "text", "") or ""
        if target_text not in text:
            self.logger.warning(f"座位面板按钮文本 '{text}' 不是 '{target_text}'，放弃点击")
            return False

        try:
            button.click()
        except Exception as e:
            self.logger.error(f"点击座位面板按钮失败: {e}")
            return False
        return True

    async def expand(self) -> bool:
        """展开座位面板；已经开着就直接返回 True。"""
        if self.handler is None:
            self.logger.warning("expand: handler 为 None")
            return False

        if self.is_expanded():
            return True

        if not self._toggle(EXPAND_LABEL):
            return False

        self.expanded = True
        self.logger.info("Expanded seat panel")
        return True

    async def collapse(self) -> bool:
        """收起座位面板；已经收着就直接返回 True。"""
        if self.handler is None:
            self.logger.warning("collapse: handler 为 None")
            return False

        if not self.is_expanded():
            return True

        if not self._toggle(COLLAPSE_LABEL):
            return False

        self.expanded = False
        self.logger.info("Collapsed seat panel")
        await asyncio.sleep(PANEL_SETTLE_SECONDS)  # 等收起动画走完
        return True

    async def expand_and_find_desks(self) -> Optional[list]:
        """展开面板并重扫出全部 6 张桌位；面板没真开就返回 None。

        展开后必须数齐 6 张桌位才算数：只渲染出一部分说明面板还在动画里或根本没
        开，拿半张面板读麦位会把「没渲染出来」误判成空位。
        """
        if not await self.expand():
            return None

        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            self.logger.error("element_finder 缺席，无法重扫桌位")
            return None

        await asyncio.sleep(PANEL_SETTLE_SECONDS)  # 等展开动画走完
        try:
            desks = finder.find_elements(SEAT_DESK_KEY)
        except Exception as e:
            self.logger.error(f"重扫座位桌位失败: {e}")
            return None
        if not desks:
            self.logger.error("Failed to find seat desks after expanding the panel")
            return None
        if len(desks) != EXPECTED_DESK_COUNT:
            self.logger.error(
                f"seat panel expansion incomplete: found {len(desks)} desks, "
                f"expected {EXPECTED_DESK_COUNT}"
            )
            return None
        return desks

    # ------------------------------------------------------------------
    # 整排滚动
    # ------------------------------------------------------------------

    DESKS_PER_ROW = 2
    VISIBLE_ROW_INDEX = 1  # 开屏就在中间的那一排，不用滚
    ANCHOR_DESK_INDEX = 2  # 拿第 3 张桌位当滑动锚点（它一定在中间那一排）
    SEAT_COUNT = EXPECTED_DESK_COUNT * DESKS_PER_ROW

    @staticmethod
    def _desk_bounds(desk) -> Optional[dict]:
        """桌位的屏幕坐标。

        desk 在生产里有两种形状：ElementWrapper 给 bounds，展开重扫拿到的 raw
        WebElement 给 location/size。两种都读不出来时返回 None（没有锚点可滚）。
        """
        bounds = getattr(desk, "bounds", None)
        if isinstance(bounds, dict):
            return bounds

        location = getattr(desk, "location", None)
        size = getattr(desk, "size", None)
        if isinstance(location, dict) and isinstance(size, dict):
            return {
                "x": location.get("x", 0),
                "y": location.get("y", 0),
                "width": size.get("width", 0),
                "height": size.get("height", 0),
            }
        return None

    def scroll_to_row(self, desk_index: int, seat_desks=None, duration: int = 100) -> bool:
        """把目标桌位所在的那一排滚进视口；已经在中间排则不动。

        一张桌位两个麦位、每排两张桌位，所以排号是 desk_index // 2。开屏可见的是
        第 2 排（desk 2/3），滚它只会把已经读到的麦位晃走 —— 所以中间排直接返回。

        Args:
            desk_index: 0..5 的桌位序号。
            seat_desks: 展开后重扫出的桌位列表。
            duration: 滑动时长（毫秒）。

        Returns:
            是否真的滑动了。
        """
        gesture = getattr(self.handler, "gesture_handler", None) if self.handler else None
        if not seat_desks or len(seat_desks) <= self.ANCHOR_DESK_INDEX:
            return False
        if gesture is None or not hasattr(gesture, "swipe"):
            return False

        row_index = desk_index // self.DESKS_PER_ROW
        if row_index == self.VISIBLE_ROW_INDEX:
            return False

        anchor = self._desk_bounds(seat_desks[self.ANCHOR_DESK_INDEX])
        if not anchor or not anchor.get("height"):
            return False

        center_x = anchor.get("x", 0) + anchor.get("width", 0) // 2
        center_y = anchor.get("y", 0) + anchor.get("height", 0) // 2
        row_height = anchor["height"]

        if row_index == 0:
            # 第 1 排被顶到视口上方，往下拉回来
            target_y = center_y + row_height
        elif row_index == 2:
            # 第 3 排在视口下方，往上推
            target_y = center_y - row_height
        else:
            return False

        try:
            gesture.swipe(center_x, center_y, center_x, target_y, duration)
        except Exception as e:
            self.logger.warning(f"滚动座位面板到第 {row_index + 1} 排失败: {e}")
            return False

        self.logger.info(f"Scrolled seat panel to row {row_index + 1} for desk {desk_index + 1}")
        return True

    async def reveal_seat(self, seat_number: int, duration: int = 100) -> Optional[list]:
        """展开面板并把某个麦位所在的那一排滚进视口，返回桌位列表。

        这是「读某个号位」的标准前置动作：面板收起时桌位根本没渲染，号位读不到。
        麦位号 1..12 映射到 desk_index = (seat_number - 1) // 2。
        """
        if not isinstance(seat_number, int) or not 1 <= seat_number <= self.SEAT_COUNT:
            self.logger.warning(f"麦位号 {seat_number} 不在 1..{self.SEAT_COUNT} 内，拒绝展开面板")
            return None

        desks = await self.expand_and_find_desks()
        if not desks:
            return None

        desk_index = (seat_number - 1) // self.DESKS_PER_ROW
        if self.scroll_to_row(desk_index, desks, duration=duration):
            # 滑动本身要等布局稳定，否则紧接着的桌位读数拿到的是滑动途中的画面
            await asyncio.sleep(PANEL_SETTLE_SECONDS)
        return desks

    # ------------------------------------------------------------------
    # UI 独占
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def ui_session(self, reason: str):
        """独占 UI 执行权，契约与 SeatObservationManager._ui_session 一致。

        展开/收起面板、滚动、点头像读弹窗全程会改页面结构。若不持锁，EventManager
        的兜底 press_back 会在这些 await 点把弹窗当成未知页面关掉，手里那个
        seat_off 句柄随之失效（StaleElementReferenceException）。

        刻意由**调用方**持有而不在本模块内部自取：ui_lock 是不可重入的
        asyncio.Lock，调用方（observe_visible_desks 等）已经持锁时再来一次就是
        自己等自己。

        controller 缺席（单元测试）时退化为不加锁；controller 在场但接口不符
        契约时直接抛错，而不是静默裸奔。
        """
        ctrl = getattr(self.handler, "controller", None) if self.handler else None
        if ctrl is None:
            yield
            return
        async with ctrl.ui_session(reason):
            yield

    # ------------------------------------------------------------------
    # 麦位头像弹窗：点名、取证、安全关窗
    # ------------------------------------------------------------------

    def _element_selector(self, element_key: str) -> Optional[str]:
        """从 config.yaml 里取元素选择器。

        生产上 handler.config 是 soul 段（AppController 用 self.config["soul"]
        构造 SoulHandler），所以 elements 通常在顶层；兼容传根的 config。
        """
        config = getattr(self.handler, "config", None)
        if isinstance(config, dict):
            elements = config.get("elements")
            if not isinstance(elements, dict):
                soul = config.get("soul")
                elements = soul.get("elements") if isinstance(soul, dict) else None
            selector = elements.get(element_key) if isinstance(elements, dict) else None
            if isinstance(selector, str) and selector.strip():
                return selector.strip()
        return self._FALLBACK_SELECTORS.get(element_key)

    def _find_child_element(self, desk, element_key: str):
        """按元素 key 在 desk 下查找子元素。

        desk 在生产里有两种形状，必须都按 *元素 key* 解析选择器：
        - 事件轮询给的 ElementWrapper：只有 lxml 快照，在本节点内按相对 XPath 查；
        - 展开重扫时 element_finder.find_elements 给的 raw WebElement。
        元素 key（如 left_state）是 resource-id 而不是 XPath，直接丢给
        ElementWrapper.find_child_element 会静默返回 None。
        """
        if desk is None:
            return None

        selector = self._element_selector(element_key)
        if selector is None:
            self.logger.debug(f"没有为麦位元素 '{element_key}' 配置选择器")
            return None

        if isinstance(desk, ElementWrapper):
            if selector.startswith("//") or selector.startswith("."):
                xpath = selector if selector.startswith(".") else f".{selector}"
            else:
                xpath = f".//*[@resource-id='{selector}']"
            try:
                return desk.find_child_element(xpath)
            except Exception:
                return None

        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            return None
        return finder.find_child_element(desk, element_key, log_failure=False)

    def _tap_avatar(self, desk, side: str, target_element) -> bool:
        """点开麦位头像弹窗。

        raw WebElement 直接点；ElementWrapper 的 click() 取不到真实元素（子元素
        wrapper 没有 element key，get_web_element() 返回 None 且静默 False），
        所以退回按 bounds 坐标点击：左侧点四分之一处，右侧点四分之三处，取高度的
        中点。
        """
        if target_element is not None and not isinstance(target_element, ElementWrapper):
            try:
                target_element.click()
                return True
            except Exception:
                pass

        bounds = self._desk_bounds(desk)
        if not bounds or not bounds.get("width") or not bounds.get("height"):
            return False
        w, h = bounds["width"], bounds["height"]
        x = bounds.get("x", 0) + (w // 4 if side == "left" else (3 * w) // 4)
        y = bounds.get("y", 0) + h // 2

        gesture = getattr(self.handler, "gesture_handler", None)
        if gesture is None or not hasattr(gesture, "click_at"):
            return False
        return bool(gesture.click_at(x, y))

    def card_still_present(self) -> bool:
        """头像名片此刻是否还在屏幕上 —— 关它的那次 back 只能由这个证据授权。

        反过来说：拿不到证据就绝不按 back。读不到昵称的弹窗不在屏幕上的可能性
        远大于它就是房间本身（RoomInfoWindow.ensure_closed 记过同一笔账）。
        """
        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            return False
        for key in self.SEAT_CARD_EVIDENCE_KEYS:
            try:
                if finder.try_find_element(key, log=False):
                    return True
            except Exception:
                continue
        return False

    def _dismiss_card(self, card: SeatCardView, seat_number: int) -> None:
        """把弹窗关回座位面板；没有证据时一次 back 都不按。

        二次取证是关键：卡片是在读完昵称之后才被别的流程关掉的（命令任务抢了锁、
        页面被切走），此刻它已经不在屏幕上了，再按 back 就是拿房间去赌。
        """
        if not card.opened:
            return

        if not self.card_still_present():
            self.logger.warning(
                f"Seat {seat_number}: seat card was already dismissed before close, "
                f"skipping press_back"
            )
            return

        key_actions = getattr(self.handler, "key_actions", None)
        if key_actions is None:
            return
        key_actions.press_back()

    @asynccontextmanager
    async def avatar_card(self, desk, side: str, seat_number: int, *, prefer_state: bool = True):
        """点开某个麦位的头像弹窗，读一次昵称，然后保证关回座位面板。

        调用方拿到的 `card.opened` 说明「弹窗是不是真的开着」，`card.name` 是读到的
        昵称（读不到就是 None，把「身份未知」留给下一轮）。无论上下文里是否抛错，
        退出时都保证：弹窗真开着就关掉，没点出弹窗就什么都不做。

        铁律：press_back 只在**按下那一刻**屏幕上有卡片时才按。房间里一次盲按
        back 就是退出派对房间，所以「没打开」「已经被关掉」两种情况都绝不能按。

        `prefer_state` 选点击目标：默认先点 ClState（房主换座后残留渲染里它最
        稳定，面板观测那条链路靠它读昵称）。要读 seat_off（「请下麦」）的链路必须
        传 False 显式点 UserView —— 没有证据证明点 ClState 弹出的名片里带着
        seat_off 按钮，���错就是静默退化成「Unable to manage seat N」。

        用法::

            async with driver.avatar_card(desk, "left", 9) as card:
                name = card.name
        """
        card = SeatCardView()
        if self.handler is None or desk is None:
            self.logger.warning(
                f"Seat {seat_number}: cannot inspect occupant (handler or desk missing)"
            )
            yield card
            return

        try:
            target_element = self._find_child_element(desk, f"{side}_state") if prefer_state else None
            if target_element is None:
                target_element = self._find_child_element(desk, f"{side}_seat")
            if not self._tap_avatar(desk, side, target_element):
                self.logger.warning(
                    f"Seat {seat_number} ({side} side): avatar tap never landed "
                    f"(no bounds / gesture failed); nothing to close"
                )
                yield card
                return

            await asyncio.sleep(SEAT_CARD_TAP_SETTLE_SECONDS)

            finder = getattr(self.handler, "element_finder", None)
            if finder is not None:
                try:
                    name_key, name_elem = finder.wait_for_any_element(
                        list(self.SEAT_CARD_EVIDENCE_KEYS), timeout=SEAT_CARD_TIMEOUT
                    )
                except Exception as e:
                    # 读数失败没有任何授权意义：当作「没打开」，绝不按 back
                    self.logger.error(f"Seat {seat_number}: reading seat card failed: {e}")
                    name_key, name_elem = None, None

                card.opened = name_elem is not None
                card.name_key = name_key
                if name_elem is not None and getattr(name_elem, "text", None):
                    card.name = name_elem.text.strip()

            if not card.opened:
                # 超时不等于没开：卡片可能刚过超时才渲染出来。留在屏幕上的卡片会
                # 挡住后面的麦位读数，甚至被下一个号位读成自己的占座人。
                card.opened = self.card_still_present()

            yield card

        finally:
            try:
                self._dismiss_card(card, seat_number)
                await asyncio.sleep(SEAT_CARD_DISMISS_SETTLE_SECONDS)
            except Exception as e:
                self.logger.warning(f"Seat {seat_number}: dismissing seat card failed: {e}")

    async def read_occupant(self, desk, side: str, seat_number: int) -> Optional[str]:
        """点开麦位弹窗读用户昵称；只有弹窗真的开了才按 back 关它。

        昵称不在麦位 DOM 里（普通用户的 TvLabelH 渲染的是麦位编号），它是「占座但
        身份未知」的唯一读数手段。读不到就返回 None，绝不拿一次盲按 back 去赌。
        """
        async with self.avatar_card(desk, side, seat_number) as card:
            return card.name
