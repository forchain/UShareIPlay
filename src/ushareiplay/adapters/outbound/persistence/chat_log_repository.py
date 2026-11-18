"""`ChatLogRepository` 的 Tortoise 实现；全局扫描保留原 JOIN 游标的 SQL 语义。"""

from datetime import datetime
from typing import Optional

from tortoise import connections

from ushareiplay.adapters.outbound.persistence.models import UserChatLog as UserChatLogModel
from ushareiplay.modules.user.domain import ChatLogEntry
from ushareiplay.modules.user.ports import ChatLogRepository


def _to_domain(row: UserChatLogModel) -> ChatLogEntry:
    return ChatLogEntry(
        id=row.id,
        user_id=row.user_id,
        content=row.content,
        created_at=row.created_at,
    )


class TortoiseChatLogRepository(ChatLogRepository):
    async def create(self, user_id: int, content: str) -> ChatLogEntry:
        row = await UserChatLogModel.create(
            user_id=user_id, content=(content or "").strip()
        )
        return _to_domain(row)

    async def count_unconsolidated(
        self, user_id: int, since: Optional[datetime] = None
    ) -> int:
        query = UserChatLogModel.filter(user_id=user_id)
        if since is not None:
            query = query.filter(created_at__gt=since)
        return await query.count()

    async def unconsolidated_logs(
        self,
        user_id: int,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[ChatLogEntry]:
        query = UserChatLogModel.filter(user_id=user_id)
        if since is not None:
            query = query.filter(created_at__gt=since)
        query = query.order_by("created_at")
        if limit is not None:
            query = query.limit(limit)
        return [_to_domain(row) for row in await query]

    async def active_user_ids_with_unconsolidated_logs(
        self, min_count: int = 1
    ) -> list[tuple[int, int]]:
        conn = connections.get("default")
        sql = """
            SELECT l.user_id, COUNT(l.id) as unmerged_count
            FROM user_chat_logs l
            LEFT JOIN user_memories m ON l.user_id = m.user_id
            WHERE m.last_consolidated_at IS NULL OR l.created_at > m.last_consolidated_at
            GROUP BY l.user_id
            HAVING COUNT(l.id) >= ?
        """
        rows = await conn.execute_query_dict(sql, [min_count])
        return [(int(r["user_id"]), int(r["unmerged_count"])) for r in rows]
