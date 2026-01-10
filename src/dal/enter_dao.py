from typing import Optional, List, Tuple
from src.models.enter import Enter
from src.dal.user_dao import UserDAO


class EnterDao:
    @staticmethod
    async def create(username: str, command: str) -> Enter:
        """Create a new enter command"""
        # Get or create user first
        user = await UserDAO.get_or_create(username=username)
        return await Enter.create(
            user=user,
            command=command
        )

    @staticmethod
    async def get_by_username(username: str) -> List[Enter]:
        """Get all enter commands for a user
        Returns:
            List[Enter]: List of enter commands ordered by id
        """
        return await Enter.filter(user__username=username).order_by('id').prefetch_related('user')

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[Enter]:
        """Get enter command by ID"""
        return await Enter.get_or_none(id=command_id).prefetch_related('user')

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """Delete an enter command by ID
        Returns:
            bool: True if a command was deleted, False otherwise
        """
        command = await Enter.get_or_none(id=command_id)
        if command:
            await command.delete()
            return True
        return False

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """Delete all enter commands for a user
        Returns:
            int: Number of commands deleted
        """
        deleted_count = await Enter.filter(user__username=username).delete()
        return deleted_count
