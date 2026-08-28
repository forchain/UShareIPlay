from datetime import datetime
from typing import List, Optional
from ushareiplay.models.user_chat_log import UserChatLog
from ushareiplay.dal.user_dao import UserDAO


class UserChatLogDAO:
    @staticmethod
    async def create(username: str, content: str) -> UserChatLog:
        """Record a chat log line under the canonical user."""
        canonical_user = await UserDAO.get_or_create(username=username)
        return await UserChatLog.create(
            user=canonical_user,
            content=(content or "").strip()
        )

    @staticmethod
    async def count_unconsolidated(user_id: int, since: Optional[datetime] = None) -> int:
        """Count unconsolidated chat logs for a user since a given datetime cursor."""
        query = UserChatLog.filter(user_id=user_id)
        if since is not None:
            query = query.filter(created_at__gt=since)
        return await query.count()

    @staticmethod
    async def get_unconsolidated_logs(
        user_id: int,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[UserChatLog]:
        """Fetch unconsolidated chat logs ordered chronologically."""
        query = UserChatLog.filter(user_id=user_id)
        if since is not None:
            query = query.filter(created_at__gt=since)
        query = query.order_by("created_at")
        if limit is not None:
            query = query.limit(limit)
        return await query

    @staticmethod
    async def get_active_user_ids_with_unconsolidated_logs(min_count: int = 1) -> List[tuple[int, int]]:
        """Find (user_id, count) for all canonical users with >= min_count unconsolidated logs.

        Returns list of (user_id, unconsolidated_count).
        """
        from tortoise import connections

        conn = connections.get("default")
        # Query users who have logs newer than their last_consolidated_at (or have no memory record yet)
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
