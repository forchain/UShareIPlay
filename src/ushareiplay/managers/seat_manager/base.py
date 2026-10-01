from ushareiplay.core.singleton import Singleton


class SeatManagerBase(Singleton):
    """Base singleton class for seat management components."""

    def __init__(self, handler=None):
        self.handler = handler

    def __str__(self):
        """Return string representation of the object for logging"""
        handler_status = "with handler" if self.handler else "no handler"
        return f"{self.__class__.__name__} ({handler_status})"

    def __repr__(self):
        """Return detailed representation of the object"""
        handler_id = id(self.handler) if self.handler else "None"
        return f"{self.__class__.__name__}(handler={handler_id})"
