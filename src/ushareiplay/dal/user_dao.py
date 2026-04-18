from typing import Optional
from ushareiplay.models import User

class UserDAO:
    @staticmethod
    async def get_or_create(username: str) -> User:
        """
        Get user by username (create if not exists), then transparently resolve
        alias users to their canonical user when `canonical_user_id` is set.
        """
        user = await UserDAO.get_or_create_raw(username=username)
        return await UserDAO.resolve_canonical(user)

    @staticmethod
    async def get_or_create_raw(username: str) -> User:
        """Get user by username or create if not exists (no canonical resolution)."""
        user, _created = await User.get_or_create(
            username=username,
            defaults={'level': 0}
        )
        return user

    @staticmethod
    async def resolve_canonical(user: User) -> User:
        """
        Resolve `user` to its canonical user (following canonical_user_id links).
        If the mapping is invalid (self-reference / cycle / missing target), fall back to `user`.
        """
        current = user
        seen_ids = set()
        while getattr(current, "canonical_user_id", None):
            if current.id in seen_ids:
                return user
            seen_ids.add(current.id)

            next_id = current.canonical_user_id
            if next_id == current.id:
                return user

            next_user = await User.get_or_none(id=next_id)
            if not next_user:
                return user
            current = next_user

        return current

    @staticmethod
    async def get_by_id(user_id: int) -> Optional[User]:
        """Get user by ID"""
        return await User.get_or_none(id=user_id)

    @staticmethod
    async def get_by_username(username: str) -> Optional[User]:
        """Get user by username"""
        return await User.get_or_none(username=username)

    @staticmethod
    async def update_level(user_id: int, level: int) -> Optional[User]:
        """Update user level"""
        user = await User.get_or_none(id=user_id)
        if user:
            user.level = level
            await user.save()
        return user
    
    @staticmethod
    async def update_level_if_lower(username: str, target_level: int) -> Optional[User]:
        """Update user level only if current level is lower than target level
        
        Args:
            username: Username to update
            target_level: Target level to set
            
        Returns:
            Updated user or None if user doesn't exist
        """
        user = await UserDAO.get_or_create(username=username)
        if user and user.level < target_level:
            user.level = target_level
            await user.save()
        return user

    @staticmethod
    async def get_all_avatar_usernames(username: str) -> set:
        """
        获取某个用户（可以是别名或主账号）所有分身的 username 集合，
        包含主账号自身。

        用于分身退出事件聚合：只有当集合中的所有账号都离线时，
        才真正触发退出事件。

        Args:
            username: 任意分身或主账号的昵称
        Returns:
            主账号 + 所有别名的 username set
        """
        raw_user = await UserDAO.get_or_create_raw(username)
        canonical = await UserDAO.resolve_canonical(raw_user)

        # 查出所有指向该主账号的别名
        aliases = await User.filter(canonical_user_id=canonical.id).values_list(
            "username", flat=True
        )

        result = set(aliases)
        result.add(canonical.username)  # 主账号本身也加进来
        return result