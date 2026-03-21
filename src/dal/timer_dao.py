from datetime import datetime
from typing import Optional, List

from src.models.timer import Timer


class TimerDAO:
    @staticmethod
    async def create(key: str, message: str, target_time: str,
                     repeat: bool = False, enabled: bool = True,
                     next_trigger: Optional[datetime] = None) -> Timer:
        """Create a new timer"""
        return await Timer.create(
            key=key,
            message=message,
            target_time=target_time,
            repeat=repeat,
            enabled=enabled,
            next_trigger=next_trigger,
        )

    @staticmethod
    async def get_or_create(key: str, defaults: dict):
        """Get existing timer or create a new one; returns (timer, created)"""
        return await Timer.get_or_create(key=key, defaults=defaults)

    @staticmethod
    async def get_by_key(key: str) -> Optional[Timer]:
        """Get timer by business key"""
        return await Timer.get_or_none(key=key)

    @staticmethod
    async def list_all() -> List[Timer]:
        """List all timers"""
        return await Timer.all()

    @staticmethod
    async def update_next_trigger(key: str, next_trigger: datetime) -> bool:
        """Update next_trigger for a timer"""
        updated = await Timer.filter(key=key).update(next_trigger=next_trigger)
        return updated > 0

    @staticmethod
    async def update_enabled(key: str, enabled: bool) -> bool:
        """Enable or disable a timer"""
        updated = await Timer.filter(key=key).update(enabled=enabled)
        return updated > 0

    @staticmethod
    async def delete_by_key(key: str) -> bool:
        """Delete timer by business key"""
        deleted = await Timer.filter(key=key).delete()
        return deleted > 0

    @staticmethod
    async def count() -> int:
        """Count total timers"""
        return await Timer.all().count()
