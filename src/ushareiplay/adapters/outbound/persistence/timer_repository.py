"""`TimerRepository` 的 Tortoise 实现：ORM 行、领域对象与历史数据迁移。"""

import json
import logging
from datetime import datetime
from pathlib import Path

from tortoise import connections
from tortoise.exceptions import IntegrityError

from ushareiplay.adapters.outbound.persistence.models.timer import Timer as TimerModel
from ushareiplay.core.paths import repo_root
from ushareiplay.modules.timer.domain import Timer, TimerKeyConflict
from ushareiplay.modules.timer.ports import TimerRepository

logger = logging.getLogger(__name__)


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

    async def prepare(self) -> None:
        await self._migrate_from_json()

    async def create(
        self,
        key: str,
        message: str,
        target_time: str,
        repeat: bool = False,
        enabled: bool = True,
        next_trigger: datetime | None = None,
    ) -> Timer:
        try:
            row = await TimerModel.create(
                key=key,
                message=message,
                target_time=target_time,
                repeat=repeat,
                enabled=enabled,
                next_trigger=next_trigger,
            )
        except IntegrityError as exc:
            raise TimerKeyConflict(key) from exc
        return self._to_domain(row)

    async def get_or_create(self, key: str, defaults: dict) -> tuple[Timer, bool]:
        row, created = await TimerModel.get_or_create(key=key, defaults=defaults)
        return self._to_domain(row), created

    async def get_by_key(self, key: str) -> Timer | None:
        row = await TimerModel.get_or_none(key=key)
        return None if row is None else self._to_domain(row)

    async def list_all(self) -> list[Timer]:
        await self._sanitize_db()
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

    async def _sanitize_db(self) -> None:
        """ORM 加载前用原生 SQL 修正不合法的 next_trigger 值（如带时区后缀）。"""
        try:
            conn = connections.get("default")
            # 去掉时区后缀（如 +00:00）并补齐单位数小时（如 1:00:00 → 01:00:00）
            rows = await conn.execute_query(
                "SELECT id, key, next_trigger FROM timer_events WHERE next_trigger IS NOT NULL"
            )
            for row in rows[1]:
                raw = row['next_trigger'] if isinstance(row, dict) else row[2]
                row_id = row['id'] if isinstance(row, dict) else row[0]
                if not isinstance(raw, str):
                    continue
                fixed = raw
                # 去掉时区后缀
                if '+' in fixed.split(' ')[-1]:
                    fixed = fixed.rsplit('+', 1)[0]
                # 补齐 "2026-03-20 1:00:00" → "2026-03-20 01:00:00"
                parts = fixed.split(' ')
                if len(parts) == 2 and len(parts[1].split(':')[0]) == 1:
                    parts[1] = '0' + parts[1]
                    fixed = ' '.join(parts)
                if fixed != raw:
                    await conn.execute_query(
                        "UPDATE timer_events SET next_trigger = ? WHERE id = ?",
                        [fixed, row_id],
                    )
        except Exception as e:
            logger.error(f"Error sanitizing timer DB: {str(e)}")

    async def _migrate_from_json(self) -> None:
        """首次运行时从 timers.json 迁移数据到数据库。"""
        if await self.count() != 0:
            return

        timers_file: Path = repo_root() / 'data' / 'timers.json'
        if not timers_file.exists():
            return

        try:
            with open(timers_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            count = 0
            for timer_key, timer_data in loaded.items():
                if not isinstance(timer_data, dict):
                    continue
                next_trigger = None
                nt_str = timer_data.get('next_trigger', '')
                if nt_str:
                    try:
                        next_trigger = datetime.fromisoformat(nt_str)
                    except ValueError:
                        pass

                _, created = await TimerModel.get_or_create(
                    key=timer_key,
                    defaults=dict(
                        message=timer_data.get('message', ''),
                        target_time=timer_data.get('target_time', ''),
                        repeat=timer_data.get('repeat', False),
                        enabled=timer_data.get('enabled', True),
                        next_trigger=next_trigger,
                    ),
                )
                if created:
                    count += 1

            logger.info(f"Migrated {count} timers from timers.json to database")
        except Exception as e:
            logger.error(f"Error migrating timers from JSON: {str(e)}")
