from .base import SeatManagerBase
from .focus import FocusManager
from .reservation import ReservationManager
from .seat_check import SeatCheckManager

class SeatManager(SeatManagerBase):
    """Global singleton instance for seat management"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(SeatManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, handler=None):
        if not self._initialized:
            super().__init__(handler)
            # Initialize components as attributes
            self.focus = FocusManager(handler)
            self.reservation = ReservationManager(handler)
            self.check = SeatCheckManager(handler)
            # Import and initialize SeatUIManager here to avoid circular import
            from .seat_ui import SeatUIManager
            self.ui = SeatUIManager(handler)
            self._initialized = True

class LazyLoader:
    """Lazy loader for seat manager to handle import-time initialization"""
    def __init__(self):
        self._initialized_seat_manager = None
        
    def __getattr__(self, name):
        # Initialize the real seat manager if this is the first access
        from ...soul.soul_handler import SoulHandler
        if not self._initialized_seat_manager:
            # For the first access, we need to find a handler
            # Since we don't have direct access, use a dummy handler for now
            # This will be replaced by the proper handler when init_seat_manager is called
            self._initialized_seat_manager = SeatManager(None)
        
        # Forward the attribute access to the real seat manager
        return getattr(self._initialized_seat_manager, name)

def init_seat_manager(handler):
    """Initialize the global seat manager instance with a proper handler"""
    global seat_manager
    # Use the singleton pattern to ensure we're updating the existing instance
    real_manager = SeatManager(handler)
    
    # If using the lazy loader, replace it with the real initialized manager
    if isinstance(seat_manager, LazyLoader):
        seat_manager = real_manager
    
    return real_manager

# Create a lazy-loading placeholder - will initialize itself on first access
seat_manager = LazyLoader() 