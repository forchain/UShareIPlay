"""Seat Management guest room guard and canonical return shapes."""
import inspect
from functools import wraps
from typing import Any, Callable, TypeVar

import ushareiplay.state.room_state as room_state

# 三种显式命名的返回形状
GUEST_ROOM_ERROR_RESULT = {'error': '他人房间不支持座位功能'}
GUEST_ROOM_CHAT_SCAN_RESULT = True
GUEST_ROOM_ENTRY_CHECK_RESULT = None

F = TypeVar('F', bound=Callable[..., Any])


def guest_room_guard(fallback_value: Any) -> Callable[[F], F]:
    """座位子系统客房守卫：处于他人房间时短路并返回显式命名的默认值。"""
    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                if room_state.RoomState.in_guest_room():
                    return fallback_value
                return await func(*args, **kwargs)
            return async_wrapper  # type: ignore
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                if room_state.RoomState.in_guest_room():
                    return fallback_value
                return func(*args, **kwargs)
            return sync_wrapper  # type: ignore

    return decorator
