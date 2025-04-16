class Singleton:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, *args, **kwargs):
        if not self._initialized:
            self._initialized = True
            self._init(*args, **kwargs)

    def _init(self, *args, **kwargs):
        """Override this method in subclasses for initialization"""
        pass 