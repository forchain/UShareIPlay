from typing import Optional, List, Tuple
from src.models.enter_event import EnterEvent
from src.dal.user_dao import UserDAO


class EnterDao:
    @staticmethod
    async def create(username: str, command: str) -> EnterEvent:
        """Create a new enter command"""
        # Get or create user first
        user = await UserDAO.get_or_create(username=username)
        return await EnterEvent.create(
            user=user,
            command=command
        )

    @staticmethod
    async def get_by_username(username: str) -> List[EnterEvent]:
        """Get all enter commands for a user
        Returns:
            List[EnterEvent]: List of enter commands ordered by id
        """
        return await EnterEvent.filter(user__username=username).order_by('id').prefetch_related('user')

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[EnterEvent]:
        """Get enter command by ID"""
        return await EnterEvent.get_or_none(id=command_id).prefetch_related('user')

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """Delete an enter command by ID
        Returns:
            bool: True if a command was deleted, False otherwise
        """
        command = await EnterEvent.get_or_none(id=command_id)
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
        deleted_count = await EnterEvent.filter(user__username=username).delete()
        return deleted_count
