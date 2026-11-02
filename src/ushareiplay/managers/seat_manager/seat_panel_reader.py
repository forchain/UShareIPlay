import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from typing import ClassVar, Optional, Tuple

from ushareiplay.core.element_wrapper import ElementWrapper


@dataclass(frozen=True)
class Reading:
    """单个座位的 DOM 读数与判定结果。

    三态语义：
    - `occupied`：存在明确的占座证据（多图头像、ClState、RankView、非空非纯数字昵称）；
    - `is_empty`：无占座证据且存在明确的空座证据（TvDefaultName、空座文案、匹配的座位编号、恰好一张头像图）；
    - `readable`：`occupied or is_empty`，两者皆假表示「看不见 / 缺证据 / 无法判定」，绝不可等同于空座。
    """

    occupied: bool
    is_empty: bool
    label: str
    has_state: bool
    has_default: bool
    has_rank: bool
    avatar_images: int

    @property
    def readable(self) -> bool:
        return self.occupied or self.is_empty


_FALLBACK_SELECTORS = {
    "seat_desk": "cn.soulapp.android:id/userRoot",
    "left_seat": "cn.soulapp.android:id/leftUserView",
    "right_seat": "cn.soulapp.android:id/rightUserView",
    "left_state": "cn.soulapp.android:id/leftClState",
    "right_state": "cn.soulapp.android:id/rightClState",
    "left_label": "cn.soulapp.android:id/leftTvLabelH",
    "right_label": "cn.soulapp.android:id/rightTvLabelH",
    "left_default_name": "cn.soulapp.android:id/leftTvDefaultName",
    "right_default_name": "cn.soulapp.android:id/rightTvDefaultName",
    "left_avatar": "cn.soulapp.android:id/leftAvatarView",
    "right_avatar": "cn.soulapp.android:id/rightAvatarView",
    "left_rank": "cn.soulapp.android:id/leftRankView",
    "right_rank": "cn.soulapp.android:id/rightRankView",
    "empty_seat": "cn.soulapp.android:id/leftTvDefaultName",
}


class SeatPanelReader:
    """座位面板的唯一读数器与 UI 锁门面。

    集中管理：
    1. 占座与空座的 DOM 证据判定（唯一占座判据，三态 Reading）；
    2. 桌位与座位的几何计算（屏幕点击落点与头像弹窗落点）；
    3. UI 会话租赁与重入控制（ui_session / holds_session / busy_elsewhere / can_probe_ui）。
    """

    EMPTY_SEAT_LABELS: ClassVar[Tuple[str, ...]] = ("点击入座", "入座")
    IMAGE_VIEW_CLASS: ClassVar[str] = "android.widget.ImageView"
    _FALLBACK_SELECTORS: ClassVar[dict[str, str]] = _FALLBACK_SELECTORS

    def __init__(self, handler=None):
        self._handler = handler
        self._logger = None
        self._session_depths: dict[asyncio.Task, int] = {}

    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, value):
        self._handler = value
        self._logger = getattr(value, "logger", None)

    @property
    def logger(self):
        if self._logger is None:
            self._logger = (
                getattr(self._handler, "logger", None)
                or logging.getLogger("ushareiplay.seat_panel_reader")
            )
        return self._logger

    @property
    def controller(self):
        if self._handler:
            return getattr(self._handler, "controller", None)
        return None

    # ------------------------------------------------------------------
    # UI 会话与独占锁租赁
    # ------------------------------------------------------------------

    @property
    def holds_session(self) -> bool:
        """当前 task 是否通过本 reader 持有会话。"""
        try:
            task = asyncio.current_task()
        except RuntimeError:
            return False
        if task is None:
            return False
        return self._session_depths.get(task, 0) > 0

    def _lock_owner(self):
        ctrl = self.controller
        if ctrl is None:
            return None
        return getattr(ctrl, "_ui_lock_owner", None) or getattr(ctrl, "_owner", None)

    @property
    def busy_elsewhere(self) -> bool:
        """UI 锁是否被并非当前 reader 会话的其他流程持有。"""
        ctrl = self.controller
        if ctrl is None:
            return False
        ui_lock = getattr(ctrl, "ui_lock", None)
        if ui_lock is None or not ui_lock.locked():
            return False
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        if task is not None and self._session_depths.get(task, 0) > 0:
            return False
        return True

    @property
    def can_probe_ui(self) -> bool:
        """是否允许探测 UI（自己持锁，或无人驱动屏幕）。"""
        return self.holds_session or not self.busy_elsewhere

    def _is_locked_by_other_task(self, task) -> bool:
        ctrl = self.controller
        if ctrl is None:
            return False
        ui_lock = getattr(ctrl, "ui_lock", None)
        if ui_lock is None or not ui_lock.locked():
            return False
        owner = self._lock_owner()
        if owner is not None:
            return owner is not task
        if task is not None:
            return self._session_depths.get(task, 0) == 0
        return True

    @asynccontextmanager
    async def session(self, reason: str = "", *, skip_if_busy: bool = False):
        """独占 UI 执行权。

        - 委托给 handler.controller.ui_session(reason)；
        - controller 缺席时退化为不加锁；
        - skip_if_busy=True 时，若有其他 task 持锁则直出 yield False；否则 yield True；
        - 同 task 嵌套进入直通并计数。
        """
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None

        current_depth = self._session_depths.get(task, 0) if task else 0
        if current_depth > 0:
            self._session_depths[task] = current_depth + 1
            try:
                yield True
            finally:
                new_depth = self._session_depths[task] - 1
                if new_depth <= 0:
                    self._session_depths.pop(task, None)
                else:
                    self._session_depths[task] = new_depth
            return

        ctrl = self.controller
        if ctrl is None:
            if task:
                self._session_depths[task] = 1
            try:
                yield True
            finally:
                if task:
                    self._session_depths.pop(task, None)
            return

        if skip_if_busy and self.busy_elsewhere:
            yield False
            return

        async with ctrl.ui_session(reason):
            if task:
                self._session_depths[task] = 1
            try:
                yield True
            finally:
                if task:
                    self._session_depths.pop(task, None)

    # ------------------------------------------------------------------
    # DOM 元素与选择器
    # ------------------------------------------------------------------

    def _element_selector(self, element_key: str) -> Optional[str]:
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

    def find_child_element(self, desk, element_key: str):
        """按 config.yaml 的元素 key 在 desk 下查找子元素。

        支持 ElementWrapper 快照与 raw WebElement，并兼容测试替身的属性注入。
        """
        if desk is None:
            return None

        selector = self._element_selector(element_key)
        if selector is None:
            self.logger.debug(f"No configured selector for seat element '{element_key}'")
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
        if finder is not None and hasattr(finder, "find_child_element"):
            elem = finder.find_child_element(desk, element_key, log_failure=False)
            if elem is not None:
                return elem

        # 兼容测试替身中的直接属性挂载
        if hasattr(desk, element_key):
            return getattr(desk, element_key)

        return None

    _find_child_element = find_child_element

    def _avatar_image_count(self, desk, side: str) -> int:
        avatar = self.find_child_element(desk, f"{side}_avatar")
        if not isinstance(avatar, ElementWrapper):
            return 0
        xpath = (
            f".//*[self::{self.IMAGE_VIEW_CLASS} or self::ImageView "
            f"or @class='{self.IMAGE_VIEW_CLASS}' or @class='ImageView']"
        )
        return len(avatar.find_child_elements(xpath))

    def _get_label_text(self, desk, side: str) -> str:
        elem = self.find_child_element(desk, f"{side}_label")
        if elem and hasattr(elem, "text"):
            return elem.text or ""
        return ""

    @staticmethod
    def _is_seat_number_label(label: str) -> bool:
        return label.isdigit() and 1 <= int(label) <= 12

    # ------------------------------------------------------------------
    # 占座判定与 DOM 读数
    # ------------------------------------------------------------------

    def read(self, desk, side: str, seat_number: Optional[int] = None) -> Reading:
        """单次 DOM 遍历获取判定结果。

        正向占座证据优先；若无正向证据且有明确空座证据，判定为空座；否则判定为不可读（unreadable）。
        """
        label = self._get_label_text(desk, side)
        avatar_images = self._avatar_image_count(desk, side)
        has_state = self.find_child_element(desk, f"{side}_state") is not None
        has_default = self.find_child_element(desk, f"{side}_default_name") is not None
        has_rank = self.find_child_element(desk, f"{side}_rank") is not None

        cleaned_label = label.strip()

        occupied = False
        if avatar_images > 1 or has_state or has_rank:
            occupied = True
        elif (
            bool(cleaned_label)
            and not self._is_seat_number_label(cleaned_label)
            and cleaned_label not in self.EMPTY_SEAT_LABELS
        ):
            occupied = True

        is_empty = False
        if not occupied:
            if has_default:
                is_empty = True
            elif cleaned_label in self.EMPTY_SEAT_LABELS:
                is_empty = True
            elif self._is_seat_number_label(cleaned_label):
                is_empty = seat_number is None or int(cleaned_label) == seat_number
            elif avatar_images == 1:
                is_empty = True

        return Reading(
            occupied=occupied,
            is_empty=is_empty,
            label=label,
            has_state=has_state,
            has_default=has_default,
            has_rank=has_rank,
            avatar_images=avatar_images,
        )

    # ------------------------------------------------------------------
    # 几何计算
    # ------------------------------------------------------------------

    def _desk_bounds(self, desk) -> Optional[dict]:
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

    def tap_point(self, desk, side: str) -> Optional[Tuple[int, int]]:
        """头像弹窗的点击落点（唯一生产公式）：左座 1/4 处，右座 3/4 处，纵向中点。"""
        bounds = self._desk_bounds(desk)
        if not bounds or not bounds.get("width") or not bounds.get("height"):
            return None
        w = bounds["width"]
        h = bounds["height"]
        x = bounds.get("x", 0) + (w // 4 if side == "left" else (3 * w) // 4)
        y = bounds.get("y", 0) + h // 2
        return (x, y)

    def where(self, desk, side: str) -> Optional[Tuple[int, int]]:
        """座位在屏幕上的点击落点：优先取座位元素中心，缺席退到 tap_point。"""
        seat_element = getattr(desk, "seat_element", None) or self.find_child_element(
            desk, f"{side}_seat"
        )
        if seat_element is not None:
            seat_bounds = self._desk_bounds(seat_element)
            if seat_bounds and seat_bounds.get("width") and seat_bounds.get("height"):
                return (
                    seat_bounds.get("x", 0) + seat_bounds["width"] // 2,
                    seat_bounds.get("y", 0) + seat_bounds["height"] // 2,
                )
        return self.tap_point(desk, side)
