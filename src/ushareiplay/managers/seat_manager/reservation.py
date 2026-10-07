"""麦位预留的旧句柄 —— 实现已并入 `SeatSubsystem`（票 #400）。

预留/取消预留现在直接走 DAL 并由子系统自己清位，不再经由 SeatCheckManager 中转
（也不再需要单独的 SeatUIManager 层）。保留本类只为了让既有调用方继续可用
（#402 删除）。
"""

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.seat_manager.subsystem import SubsystemHandle


class ReservationManager(SubsystemHandle, Singleton):
    """预留数据的向后兼容句柄（#400 合并，#402 删除）。"""

    def __init__(self, handler=None, seat_ui=None, seat_check=None):
        super().__init__(handler)
        self._seat_ui = seat_ui
        self._seat_check = seat_check

    def subsystem_kwargs(self) -> dict:
        return {"seat_ui": self._seat_ui, "seat_check": self._seat_check}

    @property
    def seat_ui(self):
        return self.subsystem.seat_ui

    @property
    def seat_check(self):
        return self.subsystem.seat_check

    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        """Reserve a seat for a user (data operation only)"""
        return await self.subsystem.reserve_seat(username, seat_number)

    async def remove_user_reservation(self, username: str) -> dict:
        """Remove a user's seat reservation (data operation only)"""
        return await self.subsystem.remove_user_reservation(username)