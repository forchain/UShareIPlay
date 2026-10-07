from ushareiplay.managers.seat_manager.base import SeatManagerBase
from ushareiplay.managers.seat_manager.reservation import ReservationManager
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem, _is_adapter
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationGateState,
    SeatObservationManager,
    SeatRescanCooldownPolicy,
)
from ushareiplay.managers.seat_manager.guard import (
    guest_room_guard,
    GUEST_ROOM_ERROR_RESULT,
    GUEST_ROOM_CHAT_SCAN_RESULT,
    GUEST_ROOM_ENTRY_CHECK_RESULT,
)
import logging

class SeatManager(SeatManagerBase):
    """座位子系统的门面：持有唯一一份实现，公开八个座位命令接口。

    合并前这里是一个逐方法转发的空壳（八个方法逐个转给四个互相独立的单例）。现在
    实现都在 `SeatSubsystem` 里，本门面只做两件事：

    - 把接线层给的四个旧单例**接到同一个子系统上**，它们由此不再是四份实现，而是
      同一份实现的四个入口（#402 删除旧单例与这些接缝）；
    - 在八个公开接口上挂客房守卫。
    """

    def __init__(
        self,
        handler=None,
        seat_ui=None,
        seat_check=None,
        reservation=None,
        seating=None,
    ):
        super().__init__(handler)
        self._subsystem = SeatSubsystem(
            handler,
            seat_ui=seat_ui,
            seat_check=seat_check,
            reservation=reservation,
            seating=seating,
        )
        self._ui = seat_ui if seat_ui is not None else (SeatUIManager.instance() if SeatUIManager.is_initialized() else None)
        self._check = seat_check if seat_check is not None else (SeatCheckManager.instance() if SeatCheckManager.is_initialized() else None)
        self._reservation = reservation if reservation is not None else (ReservationManager.instance() if ReservationManager.is_initialized() else None)
        self._seating = seating if seating is not None else (SeatingManager.instance() if SeatingManager.is_initialized() else None)

        # 只有**显式传进来**的句柄才接到本子系统上。回退解析到的单例（某处恰好已初始化）
        # 自带一套实现 —— 把它拽过来会当场换掉别人的 handler，等于把别的调用方
        # 悄悄接到本门面底下。接线层本来就把四个都显式传进来（app_controller）。
        self._subsystem.attach_handles(seat_ui=seat_ui, seat_check=seat_check)
        for handle in (seat_ui, seat_check, reservation, seating):
            if _is_adapter(handle):
                handle.bind_subsystem(self._subsystem)

        logging.getLogger('seat_manager').info(f"初始化 SeatManager 完成，handler={handler}")

    @property
    def subsystem(self) -> SeatSubsystem:
        """座位子系统的唯一实现；旧单例与本门面共用它。"""
        return self._subsystem

    @property
    def observation(self):
        """Lookup-only access to SeatObservationManager singleton if initialized."""
        return self._subsystem.observation

    @property
    def _observation(self):
        return self.observation

    @guest_room_guard(GUEST_ROOM_CHAT_SCAN_RESULT)
    async def prepare_for_chat_scan(self) -> bool:
        """Prepare seat UI state before chat history scanning."""
        return await self._subsystem.prepare_for_chat_scan()

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        """Reserve a specific seat for a user."""
        return await self._subsystem.reserve_seat(username, seat_number)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def take_seat(self, seat_number: int) -> dict:
        """Take a specific seat number."""
        return await self._subsystem.sit_at_specific_seat(seat_number)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def remove_seat_occupant(self, seat_number=None) -> dict:
        """Remove the owner or a specific seat occupant, preserving :seat 4 [n]."""
        if seat_number is None:
            return await self._subsystem.seat_off_owner()
        return await self._subsystem.seat_off_specific_seat(seat_number)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def find_owner_seat(self, force_relocate: bool = False) -> dict:
        """Find and take an available seat for the owner."""
        return await self._subsystem.find_owner_seat(force_relocate)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def remove_user_reservation(self, username: str) -> dict:
        """Remove a user's seat reservation."""
        return await self._subsystem.remove_user_reservation(username)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def accompany_user(self, target_username: str, sender_username: str = None) -> dict:
        """Find a specific user on seats and sit next to them."""
        return await self._subsystem.accompany_user(target_username, sender_username)

    @guest_room_guard(GUEST_ROOM_ENTRY_CHECK_RESULT)
    async def check_seats_on_entry(self, username: str):
        """Check seats when a user enters or returns to the party."""
        return await self._subsystem.check_seats_on_entry(username)