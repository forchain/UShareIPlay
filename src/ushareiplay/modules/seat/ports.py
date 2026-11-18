"""座位模块端口定义：仓储、面板驱动、邀请弹窗与专注变更通知。

所有端口仅使用纯领域值对象（`DeskSnapshot`、`SeatReservation`、`SeatCardView`、
`SeatInviteRow`），不泄漏 `WebElement`、`ElementWrapper` 或 Tortoise ORM 模型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ushareiplay.modules.seat.domain import (
    AvatarTapPolicy,
    DeskSnapshot,
    SeatInviteRow,
    SeatReservation,
)


class SeatReservationRepository(ABC):
    """座位预约仓储端口。"""

    @abstractmethod
    async def create(
        self,
        user_id: int,
        seat_number: int,
        duration_hours: int,
        start_time: Optional[datetime] = None,
    ) -> SeatReservation:
        """创建一条座位预约记录。"""

    @abstractmethod
    async def get_by_user_id(self, user_id: int) -> Optional[SeatReservation]:
        """获取用户最新一条预约记录；不存在返回 None。"""

    @abstractmethod
    async def get_by_seat_number(self, seat_number: int) -> Optional[SeatReservation]:
        """获取指定座位号的预约记录；不存在返回 None。"""

    @abstractmethod
    async def get_active_reservations(
        self, now: Optional[datetime] = None
    ) -> List[SeatReservation]:
        """获取当前未过期的有效预约列表。"""

    @abstractmethod
    async def remove_by_id(self, reservation_id: int) -> bool:
        """按预约 ID 删除记录；存在并删除返回 True。"""

    @abstractmethod
    async def update_start_time(
        self, reservation_id: int, new_start_time: datetime
    ) -> Optional[SeatReservation]:
        """更新预约开始时间；记录不存在返回 None。"""

    @abstractmethod
    async def remove_by_user_id(self, user_id: int) -> bool:
        """删除指定用户的全部预约记录。"""


class SeatPanelPort(ABC):
    """座位面板 UI 端口：面板状态、展开收起、滚动、桌位快照与头像弹窗交互。"""

    @property
    @abstractmethod
    def holds_session(self) -> bool:
        """当前 task 是否持有 UI 会话租赁。"""

    @property
    @abstractmethod
    def busy_elsewhere(self) -> bool:
        """UI 会话租赁是否被其他 task 持有。"""

    @property
    @abstractmethod
    def can_probe_ui(self) -> bool:
        """是否允许探测 UI。"""

    @abstractmethod
    def session(self, reason: str = "", *, skip_if_busy: bool = False):
        """独占 UI 执行权的异步上下文管理器。"""

    @property
    @abstractmethod
    def is_handler_ready(self) -> bool:
        """底层 UI 处理器是否已就绪。"""

    @abstractmethod
    def is_expanded(self) -> bool:
        """面板当前是否处于展开状态。"""

    @abstractmethod
    async def expand(self) -> bool:
        """展开座位面板。"""

    @abstractmethod
    async def collapse(self) -> bool:
        """收起座位面板。"""

    @abstractmethod
    async def expand_and_find_desk_snapshots(self) -> Optional[List[DeskSnapshot]]:
        """展开面板并读取全部 6 张桌位快照；失败返回 None。"""

    @abstractmethod
    def scroll_to_row(
        self,
        desk_index: int,
        seat_desks: Optional[List[DeskSnapshot]] = None,
        duration: int = 100,
    ) -> bool:
        """把目标桌位所在排滚进视口。"""

    @abstractmethod
    def snapshot_desks(self, raw_desks: list) -> List[DeskSnapshot]:
        """将原始桌位列表归一化为纯领域快照列表。"""

    @abstractmethod
    def find_on_screen_desks(self) -> List[DeskSnapshot]:
        """读取当前屏幕上的桌位快照列表。"""

    @abstractmethod
    def read_page_source_desks(
        self, page_source: Optional[str] = None
    ) -> List[DeskSnapshot]:
        """从页面 XML 解析桌位快照列表。"""

    @abstractmethod
    def read_focus_count(self) -> Optional[int]:
        """从界面读取专注人数；读不到返回 None。"""

    @abstractmethod
    async def read_occupant(
        self, desk_id: str, side: str, seat_number: int
    ) -> Optional[str]:
        """点开座位头像弹窗读取昵称并安全关窗。"""

    @abstractmethod
    def avatar_card(
        self,
        desk_id: str,
        side: str,
        seat_number: int,
        *,
        tap_target: AvatarTapPolicy = AvatarTapPolicy.STATE_THEN_SEAT,
    ):
        """打开座位头像弹窗的异步上下文管理器，yield SeatCardView。"""

    @abstractmethod
    def click_empty_seat(self, desk_id: str, side: str) -> Optional[str]:
        """点击空座坐标；成功返回 None，失败返回原因标识（no_bounds/no_gesture）。"""

    @abstractmethod
    def confirm_seat(self) -> dict:
        """点击确认入座按钮并收起底部抽屉。"""

    @abstractmethod
    def take_seat_by_element(self, desk_id: str, side: str) -> dict:
        """点击座位元素并确认入座。"""

    @abstractmethod
    def seat_off_by_element(
        self, desk_id: str, side: str, seat_number: int
    ) -> dict:
        """点击座位元素打开弹窗、核验占座人并请下麦。"""

    @abstractmethod
    def click_seat_off_button(self, seat_number: int) -> Optional[str]:
        """在已打开的头像弹窗中点击请下麦按钮；成功返回 None，失败返回错误原因。"""


class SeatInvitePort(ABC):
    """「邀请入座」底部弹窗 UI 端口。"""

    @abstractmethod
    async def wait_until_open(self, timeout: float = 3.0) -> bool:
        """等待邀请入座弹窗打开。"""

    @abstractmethod
    async def find_row(
        self, visible_name: str, max_pages: int = 10
    ) -> Optional[SeatInviteRow]:
        """在弹窗列表按可见昵称翻页查找目标行。"""

    @abstractmethod
    def click_invite(self, row: SeatInviteRow) -> bool:
        """点击目标行的邀请按钮。"""

    @abstractmethod
    def close(self) -> bool:
        """点击关闭按钮安全关窗。"""
