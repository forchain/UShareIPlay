"""座位领域模型、值对象、纯规则与领域异常。"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from ushareiplay.modules.shared.errors import DomainError

# ---------------------------------------------------------------------------
# 领域异常
# ---------------------------------------------------------------------------


class SeatError(DomainError):
    """座位域业务规则失败。"""


# ---------------------------------------------------------------------------
# 客房守卫与规范返回形状
# ---------------------------------------------------------------------------

GUEST_ROOM_ERROR_RESULT = {"error": "他人房间不支持座位功能"}
GUEST_ROOM_CHAT_SCAN_RESULT = True
GUEST_ROOM_ENTRY_CHECK_RESULT = None
GUEST_ROOM_EMPTY_DESK_RESULT = None

F = TypeVar("F", bound=Callable[..., Any])


def guest_room_guard(fallback_value: Any) -> Callable[[F], F]:
    """座位子系统客房守卫：处于他人房间时短路并返回显式命名的默认值。"""

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                state = args[0].room_state if args else None
                if state is not None and state.is_guest_room:
                    return fallback_value
                return await func(*args, **kwargs)

            return async_wrapper  # type: ignore
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                state = args[0].room_state if args else None
                if state is not None and state.is_guest_room:
                    return fallback_value
                return func(*args, **kwargs)

            return sync_wrapper  # type: ignore

    return decorator


# ---------------------------------------------------------------------------
# 专注人数解析与座位号判定
# ---------------------------------------------------------------------------

_FOCUS_COUNT_PATTERN = re.compile(r"(\d+)人专注中")
_FOCUS_COUNT_FALLBACK_PATTERN = re.compile(r"(\d+)")

MIN_INTERACTABLE_DESK_HEIGHT = 100


def parse_focus_count_text(text: Optional[str]) -> Optional[int]:
    """从 tvStudyRoomDesc 的文案里解析专注人数；读不出数字返回 None。"""
    if not text:
        return None
    match = _FOCUS_COUNT_PATTERN.search(text) or _FOCUS_COUNT_FALLBACK_PATTERN.search(text)
    return int(match.group(1)) if match else None


def is_seat_number_label(label: str) -> bool:
    """label 是否为 1~12 的纯数字座位号。"""
    return label.isdigit() and 1 <= int(label) <= 12


def is_bounds_interactable(bounds: Optional[dict]) -> bool:
    """桌位渲染尺寸是否具备足够的可点击交互高度。"""
    if not bounds:
        return False
    width = bounds.get("width", 0)
    height = bounds.get("height", 0)
    if height < MIN_INTERACTABLE_DESK_HEIGHT:
        return False
    return not (width > 0 and (height / width) < 0.4)


# ---------------------------------------------------------------------------
# 值对象与实体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeatReservation:
    """座位预约记录（领域实体，与 ORM 解耦）。"""

    id: int
    user_id: int
    username: str
    user_level: int
    seat_number: int
    start_time: datetime
    duration_hours: int


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


@dataclass(frozen=True)
class DeskSnapshot:
    """单张桌位的纯数据快照（不携带 WebElement / ElementWrapper）。"""

    desk_id: str
    bounds: Optional[dict]
    displayed: bool
    left: Reading
    right: Reading
    left_has_seat: bool = False
    right_has_seat: bool = False
    interactable: bool = False


@dataclass
class SeatCardView:
    """一次座位头像点名的读数结果。

    Attributes:
        opened: 弹窗确实开着（读到昵称节点，或超时后卡片仍在屏幕上）。
        name: 读到的昵称；读不到时是 None（「身份未知」留给下一轮）。
        name_key: 命中的证据元素 key，便于排障时知道是哪套名片。
    """

    opened: bool = False
    name: Optional[str] = None
    name_key: Optional[str] = None


class AvatarTapPolicy(str, Enum):
    """点名某个座位头像时的点击目标策略。"""

    SEAT_NODE = "seat_node"
    STATE_ONLY = "state_only"
    STATE_THEN_SEAT = "state_then_seat"


@dataclass
class SeatInviteRow:
    """「邀请入座」弹窗里的一行（领域值对象）。"""

    name: str
    operation: str
    invitable: bool
    element: Any = None
    operation_element: Any = field(default=None) if False else None


@dataclass
class SeatClickPlan:
    """空座的点击计划：落点坐标，或者失败原因。"""

    click_x: Optional[int] = None
    click_y: Optional[int] = None
    reason: Optional[str] = None
    occupied_label: Optional[str] = None
    desk_index: Optional[int] = None
    side: Optional[str] = None
    clicked: bool = False
