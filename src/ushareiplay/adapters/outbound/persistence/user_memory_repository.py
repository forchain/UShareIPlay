"""`UserMemoryRepository` 的 Tortoise 实现：JSON 铁律区与沉淀游标。"""

from datetime import datetime
from typing import Optional

from ushareiplay.adapters.outbound.persistence.models import UserMemory as UserMemoryModel
from ushareiplay.modules.user.domain import UserMemory
from ushareiplay.modules.user.ports import UserMemoryRepository


def _to_domain(row: UserMemoryModel) -> UserMemory:
    return UserMemory(
        directives=list(row.immutable_directives or []),
        profile=row.profile_summary or "",
        last_consolidated_at=row.last_consolidated_at,
    )


class TortoiseUserMemoryRepository(UserMemoryRepository):
    async def get(self, user_id: int) -> Optional[UserMemory]:
        row = await UserMemoryModel.get_or_none(user_id=user_id)
        return None if row is None else _to_domain(row)

    async def update(
        self,
        user_id: int,
        directives: list[str],
        profile: str,
        consolidated_at: datetime,
    ) -> UserMemory:
        row = await UserMemoryModel.get_or_none(user_id=user_id)
        if row is None:
            row = await UserMemoryModel.create(
                user_id=user_id,
                immutable_directives=directives,
                profile_summary=profile,
                last_consolidated_at=consolidated_at,
            )
            return _to_domain(row)

        row.immutable_directives = directives
        row.profile_summary = profile
        row.last_consolidated_at = consolidated_at
        await row.save()
        return _to_domain(row)
