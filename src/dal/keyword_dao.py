from typing import Optional, List
from src.models.keyword import Keyword
from src.models.user import User


class KeywordDAO:
    @staticmethod
    async def create(keyword: str, command: str, source: str, 
                     creator_id: Optional[int] = None, is_public: bool = True) -> Keyword:
        """Create a new keyword"""
        return await Keyword.create(
            keyword=keyword,
            command=command,
            source=source,
            creator_id=creator_id,
            is_public=is_public
        )

    @staticmethod
    async def get_by_keyword(keyword: str) -> Optional[Keyword]:
        """Get keyword by keyword text (with creator info)"""
        return await Keyword.get_or_none(keyword=keyword).prefetch_related('creator')

    @staticmethod
    async def get_by_keyword_and_username(keyword: str, username: str) -> Optional[Keyword]:
        """Get keyword by keyword text and creator username"""
        return await Keyword.get_or_none(
            keyword=keyword
        ).prefetch_related('creator').filter(creator__username=username)

    @staticmethod
    async def find_accessible_keyword(keyword: str, username: str) -> Optional[Keyword]:
        """Find keyword that user can execute (public or created by user)"""
        # First try to find exact match
        kw = await Keyword.get_or_none(keyword=keyword).prefetch_related('creator')
        
        if not kw:
            return None
        
        # Check if user can execute
        if kw.is_public or (kw.creator and kw.creator.username == username):
            return kw
        
        return None

    @staticmethod
    async def delete_by_keyword(keyword: str) -> bool:
        """Delete keyword by keyword text"""
        kw = await Keyword.get_or_none(keyword=keyword)
        if kw:
            await kw.delete()
            return True
        return False

    @staticmethod
    async def delete_by_source(source: str) -> int:
        """Delete all keywords by source"""
        deleted_count = await Keyword.filter(source=source).delete()
        return deleted_count

    @staticmethod
    async def update_publicity(keyword: str, is_public: bool) -> Optional[Keyword]:
        """Update keyword publicity"""
        kw = await Keyword.get_or_none(keyword=keyword).prefetch_related('creator')
        if kw:
            kw.is_public = is_public
            await kw.save()
        return kw

    @staticmethod
    async def list_by_creator(username: str) -> List[Keyword]:
        """List all keywords created by user"""
        return await Keyword.filter(creator__username=username).prefetch_related('creator')

    @staticmethod
    async def list_all() -> List[Keyword]:
        """List all keywords"""
        return await Keyword.all().prefetch_related('creator')
