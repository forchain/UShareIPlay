"""`KeywordRepository` 的内存替身；用户身份解析由注入的 UserRepository 提供。"""

from dataclasses import replace
from typing import Optional

from ushareiplay.modules.command.domain import KEYWORD_MODE_SEQUENCE, Keyword
from ushareiplay.modules.command.ports import KeywordRepository
from ushareiplay.modules.user.ports import UserRepository


class InMemoryKeywordRepository(KeywordRepository):
    def __init__(self, users: UserRepository):
        self._users = users
        self._entries: list[Keyword] = []

    def _find(self, keyword: str) -> Optional[Keyword]:
        return next((entry for entry in self._entries if entry.keyword == keyword), None)

    def _store(self, entry: Keyword, **changes) -> Keyword:
        updated = replace(entry, **changes)
        self._entries[self._entries.index(entry)] = updated
        return updated

    async def create(
        self,
        keyword: str,
        command: str,
        creator_id: Optional[int] = None,
        is_public: bool = True,
        mode: str = KEYWORD_MODE_SEQUENCE,
    ) -> Keyword:
        creator = None if creator_id is None else await self._users.get_by_id(creator_id)
        entry = Keyword(
            keyword=keyword,
            command=command,
            mode=mode,
            creator_id=creator_id,
            creator_username=creator.username.value if creator else None,
            creator_level=creator.level if creator else 0,
            is_public=is_public,
        )
        self._entries.append(entry)
        return entry

    async def get_by_keyword(self, keyword: str) -> Optional[Keyword]:
        return self._find(keyword)

    async def get_by_keyword_and_username(
        self, keyword: str, username: str
    ) -> Optional[Keyword]:
        return next(
            (
                entry
                for entry in self._entries
                if entry.keyword == keyword and entry.creator_username == username
            ),
            None,
        )

    async def find_accessible_keyword(
        self, keyword: str, username: str
    ) -> Optional[Keyword]:
        entry = self._find(keyword)
        if entry is None:
            return None
        user = await self._users.get_or_create(username)
        return entry if entry.allows(user.id) else None

    @staticmethod
    def _clean_ids(user_ids) -> list[int]:
        cleaned: list[int] = []
        for uid in user_ids or []:
            value = int(uid)
            if value > 0 and value not in cleaned:
                cleaned.append(value)
        return cleaned

    async def grant_users(self, keyword: str, user_ids: list[int]) -> Optional[Keyword]:
        entry = self._find(keyword)
        if entry is None:
            return None
        merged = list(entry.allowed_user_ids) + self._clean_ids(user_ids)
        return self._store(entry, allowed_user_ids=tuple(self._clean_ids(merged)))

    async def revoke_users(self, keyword: str, user_ids: list[int]) -> Optional[Keyword]:
        entry = self._find(keyword)
        if entry is None:
            return None
        revoke = {int(uid) for uid in user_ids or [] if str(uid).isdigit()}
        return self._store(
            entry,
            allowed_user_ids=tuple(uid for uid in entry.allowed_user_ids if uid not in revoke),
        )

    async def delete_by_keyword(self, keyword: str) -> bool:
        entry = self._find(keyword)
        if entry is None:
            return False
        self._entries.remove(entry)
        return True

    async def delete_config_keywords(self) -> int:
        kept = [entry for entry in self._entries if not entry.is_config]
        deleted = len(self._entries) - len(kept)
        self._entries = kept
        return deleted

    async def update_publicity(self, keyword: str, is_public: bool) -> Optional[Keyword]:
        entry = self._find(keyword)
        return None if entry is None else self._store(entry, is_public=is_public)

    async def list_by_creator(self, username: str) -> list[Keyword]:
        return [entry for entry in self._entries if entry.creator_username == username]

    async def list_all(self) -> list[Keyword]:
        return list(self._entries)
