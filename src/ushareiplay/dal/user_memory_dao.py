from datetime import datetime
from typing import List, Optional, Tuple
from ushareiplay.models.user_memory import UserMemory
from ushareiplay.dal.user_dao import UserDAO


class UserMemoryDAO:
    @staticmethod
    async def get_by_user_id(user_id: int) -> Optional[UserMemory]:
        """Fetch memory record by user ID."""
        return await UserMemory.get_or_none(user_id=user_id).prefetch_related("user")

    @staticmethod
    async def get_by_username(username: str) -> Optional[UserMemory]:
        """Fetch memory record by username (resolving canonical user)."""
        canonical_user = await UserDAO.get_or_create(username=username)
        return await UserMemory.get_or_none(user_id=canonical_user.id).prefetch_related("user")

    @staticmethod
    async def get_or_create(username: str) -> Tuple[UserMemory, bool]:
        """Get or create memory record for a canonical user."""
        canonical_user = await UserDAO.get_or_create(username=username)
        memory, created = await UserMemory.get_or_create(
            user=canonical_user,
            defaults={
                "immutable_directives": [],
                "profile_summary": "",
                "last_consolidated_at": None,
            }
        )
        return memory, created

    @staticmethod
    async def update_memory(
        user_id: int,
        directives: Optional[List[str]] = None,
        profile_summary: Optional[str] = None,
        consolidated_at: Optional[datetime] = None,
    ) -> Optional[UserMemory]:
        """Update directives, profile summary, and/or last_consolidated_at cursor."""
        memory = await UserMemory.get_or_none(user_id=user_id)
        if not memory:
            memory = await UserMemory.create(
                user_id=user_id,
                immutable_directives=directives if directives is not None else [],
                profile_summary=profile_summary if profile_summary is not None else "",
                last_consolidated_at=consolidated_at,
            )
            return memory

        if directives is not None:
            memory.immutable_directives = directives
        if profile_summary is not None:
            memory.profile_summary = profile_summary
        if consolidated_at is not None:
            memory.last_consolidated_at = consolidated_at

        await memory.save()
        return memory
