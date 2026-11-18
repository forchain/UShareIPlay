"""`UserRepository` 的 Tortoise 实现：ORM 行与领域对象互转。

别名解析的兜底语义与旧 `UserDAO.resolve_canonical` 保持一致：断链、自引用、
成环都回退到传入的用户，绝不把半截链表当成 canonical。
"""

import logging
from typing import Optional

from ushareiplay.adapters.outbound.persistence.models import User as UserModel
from ushareiplay.modules.user.domain import (
    OWNER_GIFT_MIN_LEVEL,
    User,
    heat_target_level,
)
from ushareiplay.modules.user.ports import UserRepository

logger = logging.getLogger("UserRepository")


def _to_domain(row: UserModel) -> User:
    return User(
        id=row.id,
        username=row.username,
        level=row.level,
        heat_value=row.heat_value or 0,
        canonical_user_id=row.canonical_user_id,
    )


def _heat_reason(level: int) -> str:
    return {
        8: "cumulative heat > 1,000,000",
        7: "cumulative heat > 100,000",
        6: "cumulative heat > 10,000",
    }.get(level, "base heat contribution")


class TortoiseUserRepository(UserRepository):
    async def get_or_create(self, username: str) -> User:
        return await self.resolve_canonical(await self.get_or_create_raw(username))

    async def get_or_create_raw(self, username: str) -> User:
        row, _created = await UserModel.get_or_create(
            username=username, defaults={"level": 0}
        )
        return _to_domain(row)

    async def resolve_canonical(self, user: User) -> User:
        current = user
        seen_ids: set[int] = set()
        while current.canonical_user_id is not None:
            if current.id in seen_ids or current.canonical_user_id == current.id:
                return user
            seen_ids.add(current.id)

            target = await self.get_by_id(current.canonical_user_id)
            if target is None:
                return user
            current = target

        return current

    async def get_by_id(self, user_id: int) -> Optional[User]:
        row = await UserModel.get_or_none(id=user_id)
        return None if row is None else _to_domain(row)

    async def get_by_username(self, username: str) -> Optional[User]:
        row = await UserModel.get_or_none(username=username)
        return None if row is None else _to_domain(row)

    async def update_level(self, user_id: int, level: int) -> Optional[User]:
        row = await UserModel.get_or_none(id=user_id)
        if row is None:
            return None

        old_level = row.level
        row.level = level
        await row.save(update_fields=["level"])
        logger.info(
            f"User ID {user_id} ('{row.username}') level updated: L{old_level} -> L{level}"
        )
        return _to_domain(row)

    async def update_level_if_lower(self, username: str, target_level: int) -> Optional[User]:
        user = await self.get_or_create(username)
        if user.level < target_level:
            old_level = user.level
            row = await UserModel.get(id=user.id)
            row.level = target_level
            await row.save(update_fields=["level"])
            logger.info(
                f"User '{user.username}' level upgraded: L{old_level} -> L{target_level} "
                f"(target: L{target_level})"
            )
            return _to_domain(row)

        logger.info(
            f"User '{user.username}' current level L{user.level} >= target L{target_level}, "
            "no level upgrade needed"
        )
        return user

    async def record_owner_gift(self, username: str) -> Optional[User]:
        logger.info(
            f"Recording owner gift for user '{username}' (minimum target: L{OWNER_GIFT_MIN_LEVEL})"
        )
        return await self.update_level_if_lower(username, OWNER_GIFT_MIN_LEVEL)

    async def record_heat_contribution(self, username: str, heat_value: int) -> Optional[User]:
        user = await self.get_or_create(username)
        if user is None:
            logger.warning(f"Failed to find or create user for heat contribution: '{username}'")
            return None

        heat_amount = max(0, int(heat_value or 0))
        old_heat = user.heat_value
        heat = old_heat + heat_amount
        target_level = heat_target_level(heat)
        reason = _heat_reason(target_level)

        row = await UserModel.get(id=user.id)
        row.heat_value = heat
        if user.level < target_level:
            old_level = user.level
            row.level = target_level
            await row.save(update_fields=["heat_value", "level"])
            logger.info(
                f"User '{user.username}' heat contribution +{heat_amount} "
                f"(cumulative: {old_heat} -> {heat}): "
                f"level upgraded L{old_level} -> L{target_level} ({reason})"
            )
        else:
            await row.save(update_fields=["heat_value"])
            logger.info(
                f"User '{user.username}' heat contribution +{heat_amount} "
                f"(cumulative: {old_heat} -> {heat}): "
                f"current level L{user.level} >= target L{target_level} ({reason}), "
                "no level upgrade needed"
            )
        return _to_domain(row)

    async def get_identity_usernames(self, username: str) -> set[str]:
        if not username:
            return set()

        user = await self.get_by_username(username)
        if user is None:
            return {username}

        canonical = await self.resolve_canonical(user)
        aliases = await UserModel.filter(canonical_user_id=canonical.id).values_list(
            "username", flat=True
        )
        return set(aliases) | {canonical.username.value, user.username.value}

    async def is_same_identity(self, requested_username: str, observed_username: str) -> bool:
        if not requested_username or not observed_username:
            return False
        if requested_username == observed_username:
            return True
        return observed_username in await self.get_identity_usernames(requested_username)

    async def get_all_avatar_usernames(self, username: str) -> set[str]:
        raw = await self.get_or_create_raw(username)
        canonical = await self.resolve_canonical(raw)
        aliases = await UserModel.filter(canonical_user_id=canonical.id).values_list(
            "username", flat=True
        )
        return set(aliases) | {canonical.username.value}

    async def get_all_associated_user_ids(self, username: str) -> list[int]:
        raw = await self.get_or_create_raw(username)
        canonical = await self.resolve_canonical(raw)
        alias_ids = await UserModel.filter(canonical_user_id=canonical.id).values_list(
            "id", flat=True
        )
        return list(set(alias_ids) | {canonical.id, raw.id})

    async def set_canonical(self, alias_id: int, canonical_id: int) -> User:
        await UserModel.filter(id=alias_id).update(canonical_user_id=canonical_id)
        return await self.get_by_id(alias_id)
