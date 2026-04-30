from typing import Optional, List
import json
from ushareiplay.models.keyword import Keyword
from ushareiplay.models.user import User
from ushareiplay.dal.user_dao import UserDAO


class KeywordDAO:
    @staticmethod
    def _parse_allowed_user_ids(raw: Optional[str]) -> List[int]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        result: List[int] = []
        for item in data:
            try:
                value = int(item)
            except Exception:
                continue
            if value > 0:
                result.append(value)
        # de-dup, stable
        seen = set()
        deduped: List[int] = []
        for v in result:
            if v in seen:
                continue
            seen.add(v)
            deduped.append(v)
        return deduped

    @staticmethod
    def _dump_allowed_user_ids(user_ids: List[int]) -> str:
        cleaned: List[int] = []
        seen = set()
        for uid in user_ids:
            try:
                v = int(uid)
            except Exception:
                continue
            if v <= 0 or v in seen:
                continue
            seen.add(v)
            cleaned.append(v)
        return json.dumps(cleaned, ensure_ascii=False)

    @staticmethod
    async def create(keyword: str, command: str, 
                     creator_id: Optional[int] = None, is_public: bool = True,
                     mode: str = Keyword.MODE_SEQUENCE) -> Keyword:
        """Create a new keyword"""
        return await Keyword.create(
            keyword=keyword,
            command=command,
            creator_id=creator_id,
            is_public=is_public,
            mode=mode
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
        
        # Check if user can execute (use canonical user id)
        effective_user = await UserDAO.get_or_create(username)
        allowed_user_ids = KeywordDAO._parse_allowed_user_ids(getattr(kw, "allowed_user_ids", None))
        allowed = (
            kw.is_public
            or (kw.creator_id is not None and kw.creator_id == effective_user.id)
            or (effective_user.id in allowed_user_ids)
        )
        if allowed:
            return kw
        
        return None

    @staticmethod
    async def grant_users(keyword: str, user_ids: List[int]) -> Optional[Keyword]:
        """Grant execute access to specific canonical user ids"""
        kw = await Keyword.get_or_none(keyword=keyword).prefetch_related("creator")
        if not kw:
            return None
        current = KeywordDAO._parse_allowed_user_ids(getattr(kw, "allowed_user_ids", None))
        merged = current + list(user_ids or [])
        kw.allowed_user_ids = KeywordDAO._dump_allowed_user_ids(merged)
        await kw.save(update_fields=["allowed_user_ids"])
        return kw

    @staticmethod
    async def revoke_users(keyword: str, user_ids: List[int]) -> Optional[Keyword]:
        """Revoke execute access from specific canonical user ids"""
        kw = await Keyword.get_or_none(keyword=keyword).prefetch_related("creator")
        if not kw:
            return None
        current = KeywordDAO._parse_allowed_user_ids(getattr(kw, "allowed_user_ids", None))
        revoke_set = {int(uid) for uid in (user_ids or []) if str(uid).isdigit()}
        remaining = [uid for uid in current if uid not in revoke_set]
        kw.allowed_user_ids = KeywordDAO._dump_allowed_user_ids(remaining)
        await kw.save(update_fields=["allowed_user_ids"])
        return kw

    @staticmethod
    async def delete_by_keyword(keyword: str) -> bool:
        """Delete keyword by keyword text"""
        kw = await Keyword.get_or_none(keyword=keyword)
        if kw:
            await kw.delete()
            return True
        return False

    @staticmethod
    async def delete_config_keywords() -> int:
        """Delete all config keywords (creator_id is None)"""
        deleted_count = await Keyword.filter(creator_id__isnull=True).delete()
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
