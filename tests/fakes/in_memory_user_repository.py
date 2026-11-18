"""`UserRepository` 的内存替身。"""

from typing import Optional

from ushareiplay.modules.user.domain import (
    OWNER_GIFT_MIN_LEVEL,
    AliasCycleError,
    User,
    follow_aliases,
    heat_target_level,
)
from ushareiplay.modules.user.ports import UserRepository


class InMemoryUserRepository(UserRepository):
    def __init__(self):
        self._users: dict[int, User] = {}
        self._ids: dict[str, int] = {}
        self._next_id = 1

    def _with(self, user: User, **changes) -> User:
        updated = User(
            id=user.id,
            username=user.username,
            level=changes.get("level", user.level),
            heat_value=changes.get("heat_value", user.heat_value),
            canonical_user_id=changes.get("canonical_user_id", user.canonical_user_id),
        )
        self._users[user.id] = updated
        return updated

    def _store(self, username: str) -> User:
        user = User(id=self._next_id, username=username)
        self._next_id += 1
        self._users[user.id] = user
        self._ids[username] = user.id
        return user

    def _lookup(self, user_id: int) -> Optional[User]:
        return self._users.get(user_id)

    async def get_or_create(self, username: str) -> User:
        return await self.resolve_canonical(await self.get_or_create_raw(username))

    async def get_or_create_raw(self, username: str) -> User:
        user_id = self._ids.get(username)
        return self._users[user_id] if user_id is not None else self._store(username)

    async def resolve_canonical(self, user: User) -> User:
        try:
            return follow_aliases(user, self._lookup)
        except AliasCycleError:
            return user

    async def get_by_id(self, user_id: int) -> Optional[User]:
        return self._users.get(user_id)

    async def get_by_username(self, username: str) -> Optional[User]:
        user_id = self._ids.get(username)
        return self._users.get(user_id) if user_id is not None else None

    async def update_level(self, user_id: int, level: int) -> Optional[User]:
        user = self._users.get(user_id)
        return None if user is None else self._with(user, level=level)

    async def update_level_if_lower(self, username: str, target_level: int) -> Optional[User]:
        user = await self.get_or_create(username)
        if user.level >= target_level:
            return user
        return self._with(user, level=target_level)

    async def record_owner_gift(self, username: str) -> Optional[User]:
        return await self.update_level_if_lower(username, OWNER_GIFT_MIN_LEVEL)

    async def record_heat_contribution(self, username: str, heat_value: int) -> Optional[User]:
        user = await self.get_or_create(username)
        heat = user.heat_value + max(0, int(heat_value or 0))
        target = heat_target_level(heat)
        return self._with(
            user,
            heat_value=heat,
            level=max(user.level, target),
        )

    async def get_identity_usernames(self, username: str) -> set[str]:
        if not username:
            return set()
        user = await self.get_by_username(username)
        if user is None:
            return {username}
        canonical = await self.resolve_canonical(user)
        aliases = {
            candidate.username.value
            for candidate in self._users.values()
            if candidate.canonical_user_id == canonical.id
        }
        return aliases | {canonical.username.value, user.username.value}

    async def is_same_identity(self, requested_username: str, observed_username: str) -> bool:
        if not requested_username or not observed_username:
            return False
        if requested_username == observed_username:
            return True
        return observed_username in await self.get_identity_usernames(requested_username)

    async def get_all_avatar_usernames(self, username: str) -> set[str]:
        raw = await self.get_or_create_raw(username)
        canonical = await self.resolve_canonical(raw)
        aliases = {
            candidate.username.value
            for candidate in self._users.values()
            if candidate.canonical_user_id == canonical.id
        }
        return aliases | {canonical.username.value}

    async def get_all_associated_user_ids(self, username: str) -> list[int]:
        raw = await self.get_or_create_raw(username)
        canonical = await self.resolve_canonical(raw)
        alias_ids = {
            candidate.id
            for candidate in self._users.values()
            if candidate.canonical_user_id == canonical.id
        }
        return list(alias_ids | {canonical.id, raw.id})

    async def set_canonical(self, alias_id: int, canonical_id: int) -> User:
        return self._with(self._users[alias_id], canonical_user_id=canonical_id)

    async def find_first_by_level(self, level: int) -> Optional[User]:
        for user_id in sorted(self._users):
            user = self._users[user_id]
            if user.level == level:
                return user
        return None
