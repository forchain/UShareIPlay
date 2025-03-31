from typing import Optional
from src.models import User

class UserDAO:
    @staticmethod
    async def get_or_create(username: str) -> User:
        """Get user by username or create if not exists"""
        user, created = await User.get_or_create(
            username=username,
            defaults={'level': 1}
        )
        return user

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