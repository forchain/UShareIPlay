"""占座/下麦/陪伴的旧句柄 —— 实现已并入 `SeatSubsystem`（票 #400）。

`sit_at_specific_seat` / `find_owner_seat` / `accompany_user` / `seat_off_*` 现在
是子系统的方法。保留本类只为了让既有调用方继续可用（#402 删除）。
"""

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.seat_manager.subsystem import SubsystemHandle


class SeatingManager(SubsystemHandle, Singleton):
    """占座流程的向后兼容句柄（#400 合并，#402 删除）。"""

    def __init__(self, handler=None, seat_ui=None, observation=None, panel_driver=None):
        super().__init__(handler)
        self._seat_ui = seat_ui
        self._observation = observation
        self._panel_driver = panel_driver

    def subsystem_kwargs(self) -> dict:
        return {
            "seat_ui": self._seat_ui,
            "observation": self._observation,
            "panel_driver": self._panel_driver,
        }

    @property
    def seat_ui(self):
        return self.subsystem.seat_ui

    @property
    def observation(self):
        return self.subsystem.observation

    @property
    def panel_driver(self):
        """座位面板的 UI 驱动：点头像、读昵称、按证据关弹窗。"""
        return self.subsystem.panel_driver

    # 占座游标归子系统所有，句柄仍然读写同一份。
    @property
    def current_desk_index(self) -> int:
        return self.subsystem.current_desk_index

    @current_desk_index.setter
    def current_desk_index(self, value):
        self.subsystem.current_desk_index = value

    @property
    def current_side(self):
        return self.subsystem.current_side

    @current_side.setter
    def current_side(self, value):
        self.subsystem.current_side = value

    async def sit_at_specific_seat(self, seat_number: int) -> dict:
        """Sit at a specific seat position (1-12) with viewport sync and page-source verification."""
        return await self.subsystem.sit_at_specific_seat(seat_number)

    async def find_owner_seat(self, force_relocate: bool = False) -> dict:
        """Find and take an available seat for owner"""
        return await self.subsystem.find_owner_seat(force_relocate)

    async def accompany_user(self, target_username: str, sender_username: str = None) -> dict:
        """Find a specific user on seats and sit next to them"""
        return await self.subsystem.accompany_user(target_username, sender_username)

    async def seat_off_owner(self) -> dict:
        """Remove the owner from their current seat."""
        return await self.subsystem.seat_off_owner()

    async def seat_off_specific_seat(self, seat_number: int) -> dict:
        """Remove the occupant from a specific seat position (1-12)."""
        return await self.subsystem.seat_off_specific_seat(seat_number)