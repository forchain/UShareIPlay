class SeatManagerBase:
    _instance = None
    _initialized = False

    def __new__(cls, handler=None):
        if cls._instance is None:
            cls._instance = super(SeatManagerBase, cls).__new__(cls)
        return cls._instance

    def __init__(self, handler=None):
        if not self._initialized:
            self.handler = handler
            self._initialized = True

    def __str__(self):
        """Return string representation of the object for logging"""
        handler_status = "with handler" if self.handler else "no handler"
        return f"{self.__class__.__name__} ({handler_status})"
        
    def __repr__(self):
        """Return detailed representation of the object"""
        handler_id = id(self.handler) if self.handler else "None"
        return f"{self.__class__.__name__}(handler={handler_id}, initialized={self._initialized})"

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance 