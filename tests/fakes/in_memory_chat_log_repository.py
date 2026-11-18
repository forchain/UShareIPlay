"""`ChatLogRepository` 的内存替身；游标与生产 SQL 一样来自 User Memory。"""

from datetime import datetime, timedelta
from typing import Optional

from ushareiplay.modules.user.domain import ChatLogEntry
from ushareiplay.modules.user.ports import ChatLogRepository, UserMemoryRepository


class InMemoryChatLogRepository(ChatLogRepository):
    def __init__(self, memories: UserMemoryRepository):
        self._memories = memories
        self._logs: list[ChatLogEntry] = []
        self._next_id = 1
        self._clock = datetime(2026, 1, 1, 0, 0, 0)

    def _tick(self) -> datetime:
        self._clock += timedelta(microseconds=1)
        return self._clock

    async def create(self, user_id: int, content: str) -> ChatLogEntry:
        entry = ChatLogEntry(
            id=self._next_id,
            user_id=user_id,
            content=(content or "").strip(),
            created_at=self._tick(),
        )
        self._next_id += 1
        self._logs.append(entry)
        return entry

    async def count_unconsolidated(
        self, user_id: int, since: Optional[datetime] = None
    ) -> int:
        return len(await self.unconsolidated_logs(user_id, since=since))

    async def unconsolidated_logs(
        self,
        user_id: int,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[ChatLogEntry]:
        logs = [
            entry
            for entry in self._logs
            if entry.user_id == user_id and (since is None or entry.created_at > since)
        ]
        return logs[:limit] if limit is not None else logs

    async def active_user_ids_with_unconsolidated_logs(
        self, min_count: int = 1
    ) -> list[tuple[int, int]]:
        counts: dict[int, int] = {}
        for user_id in {entry.user_id for entry in self._logs}:
            memory = await self._memories.get(user_id)
            since = memory.last_consolidated_at if memory else None
            count = await self.count_unconsolidated(user_id, since=since)
            if count >= min_count:
                counts[user_id] = count
        return sorted(counts.items())
