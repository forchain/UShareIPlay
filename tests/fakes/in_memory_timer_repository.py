"""`TimerRepository` 的内存替身。"""

from datetime import datetime

from ushareiplay.modules.timer.domain import Timer
from ushareiplay.modules.timer.ports import TimerRepository


class InMemoryTimerRepository(TimerRepository):
    def __init__(self):
        self._timers: dict[str, Timer] = {}

    async def create(
        self,
        key: str,
        message: str,
        target_time: str,
        repeat: bool = False,
        enabled: bool = True,
        next_trigger: datetime | None = None,
    ) -> Timer:
        timer = Timer(
            key=key,
            message=message,
            target_time=target_time,
            repeat=repeat,
            enabled=enabled,
            next_trigger=next_trigger,
        )
        self._timers[key] = timer
        return timer

    async def get_or_create(self, key: str, defaults: dict) -> tuple[Timer, bool]:
        existing = self._timers.get(key)
        if existing is not None:
            return existing, False

        timer = Timer(key=key, **defaults)
        self._timers[key] = timer
        return timer, True

    async def get_by_key(self, key: str) -> Timer | None:
        return self._timers.get(key)

    async def list_all(self) -> list[Timer]:
        return list(self._timers.values())

    async def update_next_trigger(self, key: str, next_trigger: datetime) -> bool:
        timer = self._timers.get(key)
        if timer is None:
            return False

        self._timers[key] = Timer(
            key=timer.key,
            message=timer.message,
            target_time=timer.target_time,
            repeat=timer.repeat,
            enabled=timer.enabled,
            next_trigger=next_trigger,
        )
        return True

    async def update_enabled(self, key: str, enabled: bool) -> bool:
        timer = self._timers.get(key)
        if timer is None:
            return False

        self._timers[key] = Timer(
            key=timer.key,
            message=timer.message,
            target_time=timer.target_time,
            repeat=timer.repeat,
            enabled=enabled,
            next_trigger=timer.next_trigger,
        )
        return True

    async def delete_by_key(self, key: str) -> bool:
        return self._timers.pop(key, None) is not None

    async def count(self) -> int:
        return len(self._timers)
