from ushareiplay.managers.seat_manager.base import SeatManagerBase
from ushareiplay.managers.seat_manager.reservation import ReservationManager
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
from ushareiplay.managers.seat_manager.guard import (
    guest_room_guard,
    GUEST_ROOM_ERROR_RESULT,
    GUEST_ROOM_CHAT_SCAN_RESULT,
    GUEST_ROOM_ENTRY_CHECK_RESULT,
)
import logging

class SeatManager(SeatManagerBase):
    """Global singleton instance for seat management"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        cls._instance = None

    def __init__(self, handler=None):
        # 打印更多日志，帮助调试
        logging.getLogger('seat_manager').info(f"初始化 SeatManager，handler={handler}")

        if not hasattr(self, 'initialized'):
            super().__init__(handler)
            # Initialize component managers
            # FocusManager 已迁移到事件系统，不再需要
            self._ui = SeatUIManager(handler)
            self._check = SeatCheckManager(handler, self._ui)
            self._reservation = ReservationManager(handler, self._ui, self._check)
            self._seating = SeatingManager(handler, self._ui, self.observation)
            self.initialized = True
            logging.getLogger('seat_manager').info("SeatManager 初始化完成")
        elif handler and not self.handler:
            # 如果已经初始化过，但handler为None，更新handler
            logging.getLogger('seat_manager').info(f"更新 SeatManager 的 handler: {handler}")
            self.handler = handler
            self._reservation.handler = handler
            self._check.handler = handler
            self._check._message_dispatch = None
            self._ui.handler = handler
            self._seating.handler = handler
            if hasattr(self._seating, "_observation"):
                self._seating._observation = self.observation
            if SeatObservationManager.is_initialized():
                SeatObservationManager.instance().bind_handler(handler)

    @property
    def observation(self):
        """Lookup-only access to SeatObservationManager singleton if initialized."""
        if SeatObservationManager.is_initialized():
            return SeatObservationManager.instance()
        return None

    @property
    def _observation(self):
        return self.observation

    @guest_room_guard(GUEST_ROOM_CHAT_SCAN_RESULT)
    async def prepare_for_chat_scan(self) -> bool:
        """Prepare seat UI state before chat history scanning."""
        is_expanded = self._ui.check_seats_state()
        if is_expanded:
            return await self._ui.collapse_seats()
        return True

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        """Reserve a specific seat for a user."""
        return await self._reservation.reserve_seat(username, seat_number)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def take_seat(self, seat_number: int) -> dict:
        """Take a specific seat number."""
        return await self._seating.sit_at_specific_seat(seat_number)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def remove_seat_occupant(self, seat_number=None) -> dict:
        """Remove the owner or a specific seat occupant, preserving :seat 4 [n]."""
        if seat_number is None:
            return await self._seating.seat_off_owner()
        return await self._seating.seat_off_specific_seat(seat_number)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def find_owner_seat(self, force_relocate: bool = False) -> dict:
        """Find and take an available seat for the owner."""
        return await self._seating.find_owner_seat(force_relocate)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def remove_user_reservation(self, username: str) -> dict:
        """Remove a user's seat reservation."""
        return await self._reservation.remove_user_reservation(username)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def accompany_user(self, target_username: str, sender_username: str = None) -> dict:
        """Find a specific user on seats and sit next to them."""
        return await self._seating.accompany_user(target_username, sender_username)

    @guest_room_guard(GUEST_ROOM_ENTRY_CHECK_RESULT)
    async def check_seats_on_entry(self, username: str):
        """Check seats when a user enters or returns to the party."""
        return await self._check.check_seats_on_entry(username)
