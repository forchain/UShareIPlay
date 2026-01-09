from typing import Optional
from src.models import User

class UserDAO:
    @staticmethod
    async def get_or_create(username: str) -> User:
        """Get user by username or create if not exists"""
        user, created = await User.get_or_create(
            username=username,
            defaults={'level': 0}
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
    
    @staticmethod
    async def update_level_if_lower(username: str, target_level: int) -> Optional[User]:
        """Update user level only if current level is lower than target level
        
        Args:
            username: Username to update
            target_level: Target level to set
            
        Returns:
            Updated user or None if user doesn't exist
        """
        user = await User.get_or_none(username=username)
        if user and user.level < target_level:
            user.level = target_level
            await user.save()
        return user 