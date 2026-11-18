"""座位面板的 UI 驱动（Appium 适配器，实现 `SeatPanelPort`）。"""

import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from ushareiplay.adapters.outbound.appium.locator import Locator
from ushareiplay.adapters.outbound.appium.soul.seat_panel_reader import SeatPanelReader
from ushareiplay.adapters.outbound.appium.element_wrapper import ElementWrapper
from ushareiplay.modules.seat.domain import (
    MIN_INTERACTABLE_DESK_HEIGHT,
    AvatarTapPolicy,
    DeskSnapshot,
    SeatCardView,
    is_bounds_interactable,
    parse_focus_count_text,
)
from ushareiplay.modules.seat.ports import SeatPanelPort

# 面板按钮文本：按钮上写的是「点我之后」的状态，不是当前状态。
EXPAND_LABEL = "展开"
COLLAPSE_LABEL = "收起"

# 座位头像弹窗开着的证据：弹窗自己渲染的昵称节点（两种名片各一套 id）。
SEAT_CARD_EVIDENCE_KEYS = ("souler_name", "user_name")

EXPAND_SEATS_KEY = "expand_seats"
SEAT_DESK_KEY = "seat_desk"

# 面板展开/收起都有动画，读桌位与点座位都得等它稳定下来。
PANEL_SETTLE_SECONDS = 0.5
# 展开后必须完整渲染出 6 张桌位（两列三排）才认为面板真的开了。
EXPECTED_DESK_COUNT = 6
# 重扫桌位的尝试次数：4 次 = 1 次展开 + 1 次重新展开 + 2 次渲染跟上的余量。
DESK_SCAN_MAX_ATTEMPTS = 4
# 点头像后等弹窗渲染出来的上限。
SEAT_CARD_TIMEOUT = 1.5
# 点头像后的渲染延迟。
SEAT_CARD_TAP_SETTLE_SECONDS = 0.3
# 关掉弹窗后的回场延迟。
SEAT_CARD_DISMISS_SETTLE_SECONDS = 0.2


class SeatPanelDriver(SeatPanelPort):
    """座位面板的 UI 驱动。

    Args:
        handler: SoulHandler。提供 element_finder / key_actions / gesture_handler。
    """

    EXPAND_LABEL = EXPAND_LABEL
    COLLAPSE_LABEL = COLLAPSE_LABEL
    SEAT_CARD_EVIDENCE_KEYS = SEAT_CARD_EVIDENCE_KEYS

    def __init__(self, handler=None, panel_reader=None, lease=None):
        self.expanded = False
        self._panel_reader = panel_reader
        self._lease = lease
        self._desk_registry: Dict[str, Any] = {}
        self.handler = handler

    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, value):
        self._handler = value
        if self._panel_reader is not None:
            self._panel_reader.handler = value
        self._logger = getattr(value, "logger", None)

    @property
    def is_handler_ready(self) -> bool:
        return self._handler is not None

    @property
    def panel_reader(self) -> SeatPanelReader:
        if self._panel_reader is None:
            self._panel_reader = SeatPanelReader(self.handler, lease=self._lease)
        elif self.handler and self._panel_reader.handler is not self.handler:
            self._panel_reader.handler = self.handler
        return self._panel_reader

    @property
    def logger(self):
        if self._logger is None:
            self._logger = (
                getattr(self.handler, "logger", None) or logging.getLogger("seat_panel_driver")
            )
        return self._logger

    # ------------------------------------------------------------------
    # UI 会话租赁（委托给 panel_reader）
    # ------------------------------------------------------------------

    @property
    def holds_session(self) -> bool:
        return self.panel_reader.holds_session

    @property
    def busy_elsewhere(self) -> bool:
        return self.panel_reader.busy_elsewhere

    @property
    def can_probe_ui(self) -> bool:
        return self.panel_reader.can_probe_ui

    def session(self, reason: str = "", *, skip_if_busy: bool = False):
        return self.panel_reader.session(reason, skip_if_busy=skip_if_busy)

    # ------------------------------------------------------------------
    # 桌位快照归一化与句柄解析
    # ------------------------------------------------------------------

    def _resolve_desk(self, desk_or_id: Any) -> Any:
        if isinstance(desk_or_id, DeskSnapshot):
            return self._desk_registry.get(desk_or_id.desk_id)
        if isinstance(desk_or_id, str):
            return self._desk_registry.get(desk_or_id)
        return desk_or_id

    def snapshot_desks(self, raw_desks: list) -> List[DeskSnapshot]:
        if not raw_desks:
            return []
        if len(self._desk_registry) > 256:
            self._desk_registry.clear()
        snapshots: List[DeskSnapshot] = []
        for desk in raw_desks:
            if isinstance(desk, DeskSnapshot):
                snapshots.append(desk)
                continue
            desk_id = str(id(desk))
            self._desk_registry[desk_id] = desk
            displayed = True
            if hasattr(desk, "is_displayed"):
                try:
                    displayed = bool(desk.is_displayed())
                except Exception:
                    displayed = True
            bounds = self.panel_reader._desk_bounds(desk)
            left = self.panel_reader.read(desk, "left")
            right = self.panel_reader.read(desk, "right")
            left_has_seat = self.panel_reader.find_child_element(desk, "left_seat") is not None
            right_has_seat = self.panel_reader.find_child_element(desk, "right_seat") is not None
            snapshots.append(
                DeskSnapshot(
                    desk_id=desk_id,
                    bounds=bounds,
                    displayed=displayed,
                    left=left,
                    right=right,
                    left_has_seat=left_has_seat,
                    right_has_seat=right_has_seat,
                    interactable=is_bounds_interactable(bounds),
                )
            )
        return snapshots

    def find_on_screen_desks(self) -> List[DeskSnapshot]:
        finder = getattr(self.handler, "element_finder", None)
        if finder is None or not hasattr(finder, "find_elements"):
            return []
        try:
            raw = list(finder.find_elements(SEAT_DESK_KEY) or [])
        except Exception:
            return []
        return self.snapshot_desks(raw)

    def read_page_source_desks(self, page_source: Optional[str] = None) -> List[DeskSnapshot]:
        if page_source is None:
            driver = getattr(self.handler, "driver", None)
            if driver and hasattr(driver, "page_source"):
                page_source = driver.page_source
        if not page_source:
            return []
        try:
            root = etree.fromstring(page_source.encode("utf-8"))
        except Exception as e:
            self.logger.warning(f"Failed to parse page_source XML for viewport sync: {e}")
            return []
        locator = self.panel_reader._element_locator(SEAT_DESK_KEY)
        if locator is None:
            return []
        nodes = root.xpath(locator.absolute_xpath)
        wrappers = [ElementWrapper(node, self.handler, SEAT_DESK_KEY) for node in nodes]
        return self.snapshot_desks(wrappers)

    def read_focus_count(self) -> Optional[int]:
        finder = getattr(self.handler, "element_finder", None)
        if finder is None or not hasattr(finder, "try_find_element"):
            return None
        try:
            element = finder.try_find_element("focus_count", log=False)
        except Exception as e:
            self.logger.debug(f"Failed to read focus count from UI: {e}")
            return None
        if element is None:
            return None
        return parse_focus_count_text(getattr(element, "text", ""))

    # ------------------------------------------------------------------
    # 面板状态
    # ------------------------------------------------------------------

    def _expand_button(self):
        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            return None
        return finder.try_find_element(EXPAND_SEATS_KEY, log=False)

    def is_expanded(self) -> bool:
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
            self.logger.debug(f"座位面板按钮文本 '{text}' 无法判断展开状态，沿用缓存状态")
        return self.expanded

    # ------------------------------------------------------------------
    # 展开 / 收起
    # ------------------------------------------------------------------

    def _toggle(self, target_text: str) -> bool:
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
        if self.handler is None:
            self.logger.debug("expand: handler 为 None")
            return False

        if self.is_expanded():
            return True

        if not self._toggle(EXPAND_LABEL):
            return False

        self.expanded = True
        self.logger.info("Expanded seat panel")
        return True

    async def collapse(self) -> bool:
        if self.handler is None:
            self.logger.debug("collapse: handler 为 None")
            return False

        if not self.is_expanded():
            return True

        if not self._toggle(COLLAPSE_LABEL):
            return False

        self.expanded = False
        self.logger.info("Collapsed seat panel")
        await asyncio.sleep(PANEL_SETTLE_SECONDS)
        return True

    async def expand_and_find_desks(self) -> Optional[list]:
        if not await self.expand():
            return None

        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            self.logger.error("element_finder 缺席，无法重扫桌位")
            return None

        desks = []
        for _ in range(DESK_SCAN_MAX_ATTEMPTS):
            await asyncio.sleep(PANEL_SETTLE_SECONDS)
            try:
                desks = finder.find_elements(SEAT_DESK_KEY)
            except Exception as e:
                self.logger.error(f"重扫座位桌位失败: {e}")
                return None
            if len(desks) == EXPECTED_DESK_COUNT:
                return desks
            if not self.is_expanded():
                self.logger.info("座位面板被其它流程收起，重新展开后重扫桌位")
                if not await self.expand():
                    return None

        if not desks:
            self.logger.error("Failed to find seat desks after expanding the panel")
            return None
        self.logger.error(
            f"seat panel expansion incomplete: found {len(desks)} desks, "
            f"expected {EXPECTED_DESK_COUNT}"
        )
        return None

    async def expand_and_find_desk_snapshots(self) -> Optional[List[DeskSnapshot]]:
        desks = await self.expand_and_find_desks()
        if desks is None:
            return None
        return self.snapshot_desks(desks)

    # ------------------------------------------------------------------
    # 整排滚动
    # ------------------------------------------------------------------

    DESKS_PER_ROW = 2
    VISIBLE_ROW_INDEX = 1
    ANCHOR_DESK_INDEX = 2
    SEAT_COUNT = EXPECTED_DESK_COUNT * DESKS_PER_ROW

    @staticmethod
    def _desk_bounds(desk) -> Optional[dict]:
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
        gesture = getattr(self.handler, "gesture_handler", None) if self.handler else None
        if not seat_desks or len(seat_desks) <= self.ANCHOR_DESK_INDEX:
            return False
        if gesture is None or not hasattr(gesture, "swipe"):
            return False

        row_index = desk_index // self.DESKS_PER_ROW
        if row_index == self.VISIBLE_ROW_INDEX:
            return False

        anchor_obj = seat_desks[self.ANCHOR_DESK_INDEX]
        anchor = self._desk_bounds(anchor_obj)
        if not anchor or not anchor.get("height"):
            return False

        center_x = anchor.get("x", 0) + anchor.get("width", 0) // 2
        center_y = anchor.get("y", 0) + anchor.get("height", 0) // 2
        row_height = anchor["height"]

        if row_index == 0:
            target_y = center_y + row_height
        elif row_index == 2:
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
        if not isinstance(seat_number, int) or not 1 <= seat_number <= self.SEAT_COUNT:
            self.logger.warning(f"座位号 {seat_number} 不在 1..{self.SEAT_COUNT} 内，拒绝展开面板")
            return None

        desks = await self.expand_and_find_desks()
        if not desks:
            return None

        desk_index = (seat_number - 1) // self.DESKS_PER_ROW
        if self.scroll_to_row(desk_index, desks, duration=duration):
            await asyncio.sleep(PANEL_SETTLE_SECONDS)
        return desks

    # ------------------------------------------------------------------
    # UI 独占
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def ui_session(self, reason: str):
        async with self.panel_reader.session(reason):
            yield

    # ------------------------------------------------------------------
    # 座位头像弹窗：点名、取证、安全关窗
    # ------------------------------------------------------------------

    def _element_locator(self, element_key: str) -> Optional[Locator]:
        return self.panel_reader._element_locator(element_key)

    def _find_child_element(self, desk, element_key: str):
        return self.panel_reader.find_child_element(desk, element_key)

    def is_desk_interactable(self, desk) -> bool:
        resolved = self._resolve_desk(desk)
        bounds = self._desk_bounds(resolved if resolved is not None else desk)
        return is_bounds_interactable(bounds)

    def _tap_avatar(self, desk, side: str, target_element) -> bool:
        if target_element is not None and not isinstance(target_element, ElementWrapper):
            try:
                target_element.click()
                return True
            except Exception:
                pass

        if not self.is_desk_interactable(desk):
            return False

        pt = self.panel_reader.tap_point(desk, side)
        if pt is None:
            return False
        x, y = pt

        gesture = getattr(self.handler, "gesture_handler", None)
        if gesture is None or not hasattr(gesture, "click_at"):
            return False
        return bool(gesture.click_at(x, y))

    def card_still_present(self) -> bool:
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

    def _resolve_tap_target(self, desk, side: str, tap_target: AvatarTapPolicy):
        if tap_target is AvatarTapPolicy.SEAT_NODE:
            return self._find_child_element(desk, f"{side}_seat"), True

        state_element = self._find_child_element(desk, f"{side}_state")
        if state_element is not None:
            return state_element, True
        if tap_target is AvatarTapPolicy.STATE_ONLY:
            return None, False
        return self._find_child_element(desk, f"{side}_seat"), True

    @asynccontextmanager
    async def avatar_card(
        self,
        desk,
        side: str,
        seat_number: int,
        *,
        tap_target: AvatarTapPolicy = AvatarTapPolicy.STATE_THEN_SEAT,
    ):
        resolved_desk = self._resolve_desk(desk)
        card = SeatCardView()
        if self.handler is None or resolved_desk is None:
            self.logger.debug(
                f"Seat {seat_number}: cannot inspect occupant (handler or desk missing)"
            )
            yield card
            return

        try:
            target_element, should_tap = self._resolve_tap_target(resolved_desk, side, tap_target)
            if not should_tap:
                self.logger.debug(
                    f"Seat {seat_number} ({side} side): no {side}_state node and the "
                    f"state-only tap policy forbids falling back to {side}_seat; "
                    f"nothing tapped"
                )
                yield card
                return

            if not self._tap_avatar(resolved_desk, side, target_element):
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
                    self.logger.error(f"Seat {seat_number}: reading seat card failed: {e}")
                    name_key, name_elem = None, None

                card.opened = name_elem is not None
                card.name_key = name_key
                if name_elem is not None and getattr(name_elem, "text", None):
                    card.name = name_elem.text.strip()

            if not card.opened:
                card.opened = self.card_still_present()

            yield card

        finally:
            try:
                self._dismiss_card(card, seat_number)
                await asyncio.sleep(SEAT_CARD_DISMISS_SETTLE_SECONDS)
            except Exception as e:
                self.logger.warning(f"Seat {seat_number}: dismissing seat card failed: {e}")

    async def read_occupant(self, desk, side: str, seat_number: int) -> Optional[str]:
        async with self.avatar_card(desk, side, seat_number) as card:
            return card.name

    # ------------------------------------------------------------------
    # 入座 / 清座动作（实现 SeatPanelPort）
    # ------------------------------------------------------------------

    def click_empty_seat(self, desk_id: str, side: str) -> Optional[str]:
        desk = self._resolve_desk(desk_id)
        if desk is None:
            return "no_bounds"
        point = self.panel_reader.where(desk, side)
        if point is None:
            return "no_bounds"
        click_x, click_y = point
        gesture = getattr(self.handler, "gesture_handler", None)
        if not gesture or not hasattr(gesture, "click_at"):
            return "no_gesture"
        gesture.click_at(click_x, click_y)
        return None

    def confirm_seat(self) -> dict:
        if self.handler is None:
            return {"error": "Handler not initialized"}
        try:
            confirm_button = self.handler.element_finder.wait_for_element_clickable("confirm_seat")
            if not confirm_button:
                self.handler.logger.error("Failed to find confirm button")
                return {"error": "Failed to find confirm button"}

            confirm_button.click()
            self.handler.logger.info("Confirmed seat selection")
            bottom_drawer = self.handler.element_finder.wait_for_element_clickable("bottom_drawer")
            if bottom_drawer:
                self.handler.gesture_handler.click_element_at(bottom_drawer, 0.5, -0.1)
                self.handler.logger.info("Hide bottom drawer")
            return {"success": "Successfully took a seat"}
        except Exception as e:
            self.handler.log_error(f"Error confirming seat: {traceback.format_exc()}")
            return {"error": f"Failed to confirm seat: {str(e)}"}

    def take_seat_by_element(self, desk_id: str, side: str) -> dict:
        desk = self._resolve_desk(desk_id)
        seat_elem = self.panel_reader.find_child_element(desk, f"{side}_seat") if desk else None
        if self.handler is None or seat_elem is None:
            return {"error": "Seat element not available"}
        try:
            seat_elem.click()
            return self.confirm_seat()
        except Exception:
            self.handler.log_error(f"Error while clicking seat: {traceback.format_exc()}")
            return {"error": "Failed to click seat"}

    def seat_off_by_element(self, desk_id: str, side: str, seat_number: int) -> dict:
        desk = self._resolve_desk(desk_id)
        seat_elem = self.panel_reader.find_child_element(desk, f"{side}_seat") if desk else None
        if self.handler is None or seat_elem is None:
            return {"error": "Seat element not available"}
        try:
            seat_elem.click()
            self.handler.logger.info(f"Clicked seat {seat_number} to remove occupant")

            seat_off = self.handler.element_finder.wait_for_element_clickable("seat_off")
            if not seat_off:
                self.handler.logger.error(f"Failed to find seat off button for seat {seat_number}")
                return {"error": f"Unable to manage seat {seat_number}"}

            _key, souler_name = self.handler.element_finder.wait_for_any_element(
                ["souler_name", "user_name"]
            )
            if not souler_name:
                self.handler.logger.error(f"No souler name found for seat {seat_number}")
                return {"error": f"Failed to verify occupant on seat {seat_number}"}

            souler_name_text = souler_name.text
            seat_off.click()
            self.handler.logger.info(
                f"Successfully removed {souler_name_text} from seat {seat_number}"
            )
            return {"success": f"Successfully removed {souler_name_text} from seat {seat_number}"}
        except Exception:
            self.handler.log_error(
                f"Error while removing seat occupant: {traceback.format_exc()}"
            )
            return {"error": "Failed to remove seat occupant"}

    def click_seat_off_button(self, seat_number: int) -> Optional[str]:
        seat_off = self.handler.element_finder.wait_for_element_clickable("seat_off")
        if not seat_off:
            self.handler.logger.error(f"Failed to find seat off button for seat {seat_number}")
            return "not_found"
        seat_off.click()
        return None
