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

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance 