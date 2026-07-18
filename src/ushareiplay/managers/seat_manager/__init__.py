from ushareiplay.managers.seat_manager.base import SeatManagerBase
from ushareiplay.managers.seat_manager.reservation import ReservationManager
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
import logging

class SeatManager(SeatManagerBase):
    """Global singleton instance for seat management"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, handler=None):
        # 打印更多日志，帮助调试
        logging.getLogger('seat_manager').info(f"初始化 SeatManager，handler={handler}")
        
        if not hasattr(self, 'initialized'):
            super().__init__(handler)
            # Initialize component managers
            # FocusManager 已迁移到事件系统，不再需要
            self.ui = SeatUIManager(handler)
            self.check = SeatCheckManager(handler, self.ui)
            self.reservation = ReservationManager(handler, self.ui, self.check)
            self.seating = SeatingManager(handler, self.ui)
            self.initialized = True
            logging.getLogger('seat_manager').info("SeatManager 初始化完成")
        elif handler and not self.handler:
            # 如果已经初始化过，但handler为None，更新handler
            logging.getLogger('seat_manager').info(f"更新 SeatManager 的 handler: {handler}")
            self.handler = handler
            self.reservation.handler = handler
            self.check.handler = handler
            self.check._message_dispatch = None
            self.ui.handler = handler
            self.seating.handler = handler

    async def prepare_for_chat_scan(self) -> bool:
        """Prepare seat UI state before chat history scanning."""
        is_expanded = self.ui.check_seats_state()
        if is_expanded:
            return await self.ui.collapse_seats()
        return True

    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        """Reserve a specific seat for a user."""
        return await self.reservation.reserve_seat(username, seat_number)

    async def take_seat(self, seat_number: int) -> dict:
        """Take a specific seat number."""
        return await self.seating.sit_at_specific_seat(seat_number)

    async def remove_seat_occupant(self, seat_number=None) -> dict:
        """Remove the owner or a specific seat occupant, preserving :seat 4 [n]."""
        if seat_number is None:
            return await self.seating.seat_off_owner()
        return await self.seating.seat_off_specific_seat(seat_number)
