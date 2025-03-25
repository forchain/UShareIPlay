from .base import SeatManagerBase
from .focus import FocusManager
from .reservation import ReservationManager
from .seat_check import SeatCheckManager
from .seat_ui import SeatUIManager

class SeatManager(FocusManager, ReservationManager, SeatCheckManager, SeatUIManager):
    """Main SeatManager class that combines all functionality"""
    def __init__(self, handler=None):
        SeatManagerBase.__init__(self, handler)
        FocusManager.__init__(self, handler)
        ReservationManager.__init__(self, handler)
        SeatCheckManager.__init__(self, handler)
        SeatUIManager.__init__(self, handler) 