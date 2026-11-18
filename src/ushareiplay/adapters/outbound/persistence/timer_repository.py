"""`TimerRepository` 的 Tortoise 实现：ORM 行与领域对象互转。"""

from datetime import datetime

from ushareiplay.adapters.outbound.persistence.models.timer import Timer as TimerModel
from ushareiplay.modules.timer.domain import Timer
from ushareiplay.modules.timer.ports import TimerRepository


class TortoiseTimerRepository(TimerRepository):
    @staticmethod
    def _to_domain(row: TimerModel) -> Timer:
        return Timer(
            key=row.key,
            message=row.message,
            target_time=row.target_time,
            repeat=row.repeat,
            enabled=row.enabled,
            next_trigger=row.next_trigger,
        )

    async def create(
        self,
        key: str,
        message: str,
        target_time: str,
        repeat: bool = False,
        enabled: bool = True,
        next_trigger: datetime | None = None,
    ) -> Timer:
        row = await TimerModel.create(
            key=key,
            message=message,
            target_time=target_time,
            repeat=repeat,
            enabled=enabled,
            next_trigger=next_trigger,
        )
        return self._to_domain(row)

    async def get_or_create(self, key: str, defaults: dict) -> tuple[Timer, bool]:
        row, created = await TimerModel.get_or_create(key=key, defaults=defaults)
        return self._to_domain(row), created

    async def get_by_key(self, key: str) -> Timer | None:
        row = await TimerModel.get_or_none(key=key)
        return None if row is None else self._to_domain(row)

    async def list_all(self) -> list[Timer]:
        return [self._to_domain(row) for row in await TimerModel.all()]

    async def update_next_trigger(self, key: str, next_trigger: datetime) -> bool:
        updated = await TimerModel.filter(key=key).update(next_trigger=next_trigger)
        return updated > 0

    async def update_enabled(self, key: str, enabled: bool) -> bool:
        updated = await TimerModel.filter(key=key).update(enabled=enabled)
        return updated > 0

    async def delete_by_key(self, key: str) -> bool:
        deleted = await TimerModel.filter(key=key).delete()
        return deleted > 0

    async def count(self) -> int:
        return await TimerModel.all().count()
