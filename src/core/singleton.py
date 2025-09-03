"""
Singleton base class implementation
Provides a thread-safe singleton pattern for manager classes
"""

import threading
from typing import TypeVar, Type

T = TypeVar('T')


class Singleton:
    """
    Thread-safe singleton base class
    Usage: class MyClass(Singleton): pass
    Access: MyClass.instance()
    """
    
    _instances = {}
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super(Singleton, cls).__new__(cls)
        return cls._instances[cls]
    
    @classmethod
    def instance(cls: Type[T], *args, **kwargs) -> T:
        """
        Get the singleton instance of the class
        Args:
            *args: Arguments to pass to __init__ if instance doesn't exist
            **kwargs: Keyword arguments to pass to __init__ if instance doesn't exist
        Returns:
            T: The singleton instance
        """
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = cls(*args, **kwargs)
        return cls._instances[cls]
    
    @classmethod
    def reset_instance(cls):
        """
        Reset the singleton instance (mainly for testing)
        """
        with cls._lock:
            if cls in cls._instances:
                del cls._instances[cls]
