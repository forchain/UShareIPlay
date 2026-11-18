"""`UserMemoryRepository` 的内存替身。"""

from datetime import datetime
from typing import Optional

from ushareiplay.modules.user.domain import UserMemory
from ushareiplay.modules.user.ports import UserMemoryRepository


class InMemoryUserMemoryRepository(UserMemoryRepository):
    def __init__(self):
        self._memories: dict[int, UserMemory] = {}

    async def get(self, user_id: int) -> Optional[UserMemory]:
        return self._memories.get(user_id)

    async def update(
        self,
        user_id: int,
        directives: list[str],
        profile: str,
        consolidated_at: datetime,
    ) -> UserMemory:
        memory = UserMemory(
            directives=list(directives),
            profile=profile,
            last_consolidated_at=consolidated_at,
        )
        self._memories[user_id] = memory
        return memory
