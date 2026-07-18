import threading
import weakref


class SingletonError(RuntimeError):
    """Raised when a singleton is created or accessed through the wrong API."""


class SingletonMeta(type):
    """所有单例类共用的元类"""
    _lock = threading.RLock()
    _registry: weakref.WeakSet[type] = weakref.WeakSet()
    _initialization_order: list[weakref.ReferenceType[type]] = []

    def __init__(cls, name, bases, namespace, **kwargs):
        super().__init__(name, bases, namespace, **kwargs)
        if any(isinstance(base, SingletonMeta) for base in bases):
            SingletonMeta._registry.add(cls)

    def __call__(cls, *args, **kwargs):
        raise SingletonError(
            f"{cls.__name__} singleton creation is restricted. "
            f"Use {cls.__name__}.initialize(...)."
        )

    def _initialize(cls, *args, **kwargs):
        with SingletonMeta._lock:
            if cls.__dict__.get("_singleton_initialized", False):
                raise SingletonError(
                    f"{cls.__name__} singleton already initialized. "
                    f"Use {cls.__name__}.instance() to access it."
                )

            instance = type.__call__(cls, *args, **kwargs)
            cls._instance = instance
            cls._singleton_initialized = True
            SingletonMeta._initialization_order.append(weakref.ref(cls))
            return instance


class Singleton(metaclass=SingletonMeta):
    """单例基类，子类只需继承即可"""

    @classmethod
    def initialize(cls, *args, **kwargs):
        """Create this singleton exactly once."""
        return SingletonMeta._initialize(cls, *args, **kwargs)

    @classmethod
    def instance(cls):
        """Return an initialized singleton without creating one implicitly."""
        if not cls.__dict__.get("_singleton_initialized", False):
            raise SingletonError(
                f"{cls.__name__} has not been initialized. "
                f"Call {cls.__name__}.initialize(...) first."
            )
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset one singleton. Intended for tests and process restart only."""
        with SingletonMeta._lock:
            cls._instance = None
            cls._singleton_initialized = False

    @classmethod
    def reset_all_instances(cls) -> None:
        """Reset initialized singletons in reverse creation order."""
        with SingletonMeta._lock:
            initialized = []
            for class_ref in SingletonMeta._initialization_order:
                singleton_class = class_ref()
                if singleton_class is not None:
                    initialized.append(singleton_class)

            for singleton_class in reversed(initialized):
                singleton_class.reset_instance()
            SingletonMeta._initialization_order.clear()
