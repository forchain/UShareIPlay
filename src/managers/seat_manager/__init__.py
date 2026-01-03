from .base import SeatManagerBase
from .reservation import ReservationManager
from .seat_check import SeatCheckManager
from .seat_ui import SeatUIManager
from .seating import SeatingManager
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
            self.reservation = ReservationManager(handler)
            self.check = SeatCheckManager(handler)
            self.ui = SeatUIManager(handler)
            self.seating = SeatingManager(handler)
            self.initialized = True
            logging.getLogger('seat_manager').info("SeatManager 初始化完成")
        elif handler and not self.handler:
            # 如果已经初始化过，但handler为None，更新handler
            logging.getLogger('seat_manager').info(f"更新 SeatManager 的 handler: {handler}")
            self.handler = handler
            self.reservation.handler = handler
            self.check.handler = handler
            self.ui.handler = handler
            self.seating.handler = handler

# Create a default instance with a None handler
# This ensures seat_manager is never None, components will be properly initialized later
seat_manager = SeatManager(None)

def init_seat_manager(handler):
    """Initialize the global seat manager instance"""
    global seat_manager
    # Since we're using the singleton pattern, this will update the existing instance
    logging.getLogger('seat_manager').info(f"调用 init_seat_manager，handler={handler}")
    seat_manager = SeatManager(handler)
    
    # 额外检查确保所有子管理器的handler都已正确设置
    if not seat_manager.handler:
        logging.getLogger('seat_manager').error("初始化后 seat_manager.handler 仍为 None")
    if not seat_manager.ui.handler:
        logging.getLogger('seat_manager').error("初始化后 seat_manager.ui.handler 仍为 None")
        
    return seat_manager 