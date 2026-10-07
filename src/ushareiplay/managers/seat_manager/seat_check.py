"""进房检查与占座人清退的旧句柄 —— 实现已并入 `SeatSubsystem`（票 #400）。

`check_seats_on_entry` / `check_user_specific_seat` 现在是子系统的方法：预留落库
之后清位不再经由本单例绕一圈。保留本类只为了让既有调用方继续可用（#402 删除）。
"""

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.seat_manager.subsystem import SubsystemHandle


class SeatCheckManager(SubsystemHandle, Singleton):
    """进房检查的向后兼容句柄（#400 合并，#402 删除）。"""

    def __init__(self, handler=None, seat_ui=None, panel_driver=None):
        super().__init__(handler)
        self._seat_ui = seat_ui
        self._panel_driver = panel_driver

    def subsystem_kwargs(self) -> dict:
        return {"seat_ui": self._seat_ui, "panel_driver": self._panel_driver}

    @property
    def seat_ui(self):
        return self.subsystem.seat_ui

    @property
    def panel_driver(self):
        """座位面板的 UI 驱动：点名片、读占座人昵称、按证据关弹窗。"""
        return self.subsystem.panel_driver

    @property
    def message_dispatch(self):
        return self.subsystem.message_dispatch

    @message_dispatch.setter
    def message_dispatch(self, value):
        self.subsystem._message_dispatch = value

    # 既有测试直接在实例上挂 _message_dispatch，接缝必须留着（#402 一起删）。
    @property
    def _message_dispatch(self):
        return self.subsystem._message_dispatch

    @_message_dispatch.setter
    def _message_dispatch(self, value):
        self.subsystem._message_dispatch = value

    async def check_seats_on_entry(self, username: str = None):
        """Check seats when user enters the party"""
        return await self.subsystem.check_seats_on_entry(username)

    async def check_user_specific_seat(self, username: str, seat_number: int):
        return await self.subsystem.check_user_specific_seat(username, seat_number)