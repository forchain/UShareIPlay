"""`KeywordRepository` 的 Tortoise 实现：ORM 行与领域对象互转。"""

import json
from typing import Optional

from ushareiplay.adapters.outbound.persistence.models.keyword import Keyword as KeywordModel
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.modules.command.domain import KEYWORD_MODE_SEQUENCE, Keyword
from ushareiplay.modules.command.ports import KeywordRepository


def _parse_allowed_user_ids(raw: Optional[str]) -> tuple[int, ...]:
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except Exception:
        return ()
    if not isinstance(data, list):
        return ()
    result: list[int] = []
    for item in data:
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0 and value not in result:
            result.append(value)
    return tuple(result)


def _dump_allowed_user_ids(user_ids: list[int]) -> str:
    cleaned: list[int] = []
    for uid in user_ids:
        try:
            value = int(uid)
        except Exception:
            continue
        if value > 0 and value not in cleaned:
            cleaned.append(value)
    return json.dumps(cleaned, ensure_ascii=False)


class TortoiseKeywordRepository(KeywordRepository):
    def __init__(self, users: Optional[TortoiseUserRepository] = None):
        self._users = users or TortoiseUserRepository()

    @staticmethod
    def _to_domain(row: KeywordModel) -> Keyword:
        creator = row.creator
        return Keyword(
            keyword=row.keyword,
            command=row.command,
            mode=row.mode or KEYWORD_MODE_SEQUENCE,
            creator_id=row.creator_id,
            creator_username=creator.username if creator else None,
            creator_level=creator.level if creator else 0,
            is_public=row.is_public,
            allowed_user_ids=_parse_allowed_user_ids(row.allowed_user_ids),
        )

    async def create(
        self,
        keyword: str,
        command: str,
        creator_id: Optional[int] = None,
        is_public: bool = True,
        mode: str = KEYWORD_MODE_SEQUENCE,
    ) -> Keyword:
        row = await KeywordModel.create(
            keyword=keyword,
            command=command,
            creator_id=creator_id,
            is_public=is_public,
            mode=mode,
        )
        creator = None if creator_id is None else await self._users.get_by_id(creator_id)
        return Keyword(
            keyword=row.keyword,
            command=row.command,
            mode=row.mode,
            creator_id=row.creator_id,
            creator_username=creator.username.value if creator else None,
            creator_level=creator.level if creator else 0,
            is_public=row.is_public,
        )

    async def get_by_keyword(self, keyword: str) -> Optional[Keyword]:
        row = await KeywordModel.get_or_none(keyword=keyword).prefetch_related("creator")
        return None if row is None else self._to_domain(row)

    async def get_by_keyword_and_username(
        self, keyword: str, username: str
    ) -> Optional[Keyword]:
        row = (
            await KeywordModel.get_or_none(keyword=keyword)
            .prefetch_related("creator")
            .filter(creator__username=username)
        )
        return None if row is None else self._to_domain(row)

    async def find_accessible_keyword(
        self, keyword: str, username: str
    ) -> Optional[Keyword]:
        row = await KeywordModel.get_or_none(keyword=keyword).prefetch_related("creator")
        if row is None:
            return None
        user = await self._users.get_or_create(username)
        domain = self._to_domain(row)
        return domain if domain.allows(user.id) else None

    async def grant_users(self, keyword: str, user_ids: list[int]) -> Optional[Keyword]:
        row = await KeywordModel.get_or_none(keyword=keyword).prefetch_related("creator")
        if row is None:
            return None
        merged = list(_parse_allowed_user_ids(row.allowed_user_ids)) + list(user_ids or [])
        row.allowed_user_ids = _dump_allowed_user_ids(merged)
        await row.save(update_fields=["allowed_user_ids"])
        return self._to_domain(row)

    async def revoke_users(self, keyword: str, user_ids: list[int]) -> Optional[Keyword]:
        row = await KeywordModel.get_or_none(keyword=keyword).prefetch_related("creator")
        if row is None:
            return None
        revoke = {int(uid) for uid in (user_ids or []) if str(uid).isdigit()}
        remaining = [uid for uid in _parse_allowed_user_ids(row.allowed_user_ids) if uid not in revoke]
        row.allowed_user_ids = _dump_allowed_user_ids(remaining)
        await row.save(update_fields=["allowed_user_ids"])
        return self._to_domain(row)

    async def delete_by_keyword(self, keyword: str) -> bool:
        row = await KeywordModel.get_or_none(keyword=keyword)
        if row is None:
            return False
        await row.delete()
        return True

    async def delete_config_keywords(self) -> int:
        return await KeywordModel.filter(creator_id__isnull=True).delete()

    async def update_publicity(self, keyword: str, is_public: bool) -> Optional[Keyword]:
        row = await KeywordModel.get_or_none(keyword=keyword).prefetch_related("creator")
        if row is None:
            return None
        row.is_public = is_public
        await row.save()
        return self._to_domain(row)

    async def list_by_creator(self, username: str) -> list[Keyword]:
        rows = await KeywordModel.filter(creator__username=username).prefetch_related("creator")
        return [self._to_domain(row) for row in rows]

    async def list_all(self) -> list[Keyword]:
        rows = await KeywordModel.all().prefetch_related("creator")
        return [self._to_domain(row) for row in rows]
