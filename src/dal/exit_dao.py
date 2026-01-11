from typing import Optional, List
from src.models.exit_event import ExitEvent
from src.dal.user_dao import UserDAO


class ExitDao:
    @staticmethod
    async def create(username: str, command: str) -> ExitEvent:
        """Create a new exit command"""
        # Get or create user first
        user = await UserDAO.get_or_create(username=username)
        return await ExitEvent.create(
            user=user,
            command=command
        )

    @staticmethod
    async def get_by_username(username: str) -> List[ExitEvent]:
        """Get all exit commands for a user
        Returns:
            List[ExitEvent]: List of exit commands ordered by id
        """
        return await ExitEvent.filter(user__username=username).order_by('id').prefetch_related('user')

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[ExitEvent]:
        """Get exit command by ID"""
        return await ExitEvent.get_or_none(id=command_id).prefetch_related('user')

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """Delete an exit command by ID
        Returns:
            bool: True if a command was deleted, False otherwise
        """
        command = await ExitEvent.get_or_none(id=command_id)
        if command:
            await command.delete()
            return True
        return False

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """Delete all exit commands for a user
        Returns:
            int: Number of commands deleted
        """
        deleted_count = await ExitEvent.filter(user__username=username).delete()
        return deleted_count
