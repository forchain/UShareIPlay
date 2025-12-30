import threading


class SingletonMeta(type):
    """所有单例类共用的元类"""
    _lock = threading.Lock()  # 确保线程安全

    def __call__(cls, *args, **kwargs):
        if not hasattr(cls, "_instance"):
            with cls._lock:  # 双重检查锁
                if not hasattr(cls, "_instance"):
                    cls._instance = super().__call__(*args, **kwargs)
        return cls._instance


class Singleton(metaclass=SingletonMeta):
    """单例基类，子类只需继承即可"""

    @classmethod
    def instance(cls, *args, **kwargs):
        # 如果实例已存在且没有传入参数，直接返回现有实例
        if hasattr(cls, "_instance") and not args and not kwargs:
            return cls._instance
        return cls(*args, **kwargs)
