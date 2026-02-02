from typing import Optional, List
from src.models.return_event import ReturnEvent
from src.dal.user_dao import UserDAO


class ReturnDao:
    @staticmethod
    async def create(username: str, command: str) -> ReturnEvent:
        """Create a new return command"""
        user = await UserDAO.get_or_create(username=username)
        return await ReturnEvent.create(
            user=user,
            command=command
        )

    @staticmethod
    async def get_by_username(username: str) -> List[ReturnEvent]:
        """Get all return commands for a user
        Returns:
            List[ReturnEvent]: List of return commands ordered by id
        """
        return await ReturnEvent.filter(user__username=username).order_by('id').prefetch_related('user')

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[ReturnEvent]:
        """Get return command by ID"""
        return await ReturnEvent.get_or_none(id=command_id).prefetch_related('user')

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """Delete a return command by ID
        Returns:
            bool: True if a command was deleted, False otherwise
        """
        command = await ReturnEvent.get_or_none(id=command_id)
        if command:
            await command.delete()
            return True
        return False

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """Delete all return commands for a user
        Returns:
            int: Number of commands deleted
        """
        deleted_count = await ReturnEvent.filter(user__username=username).delete()
        return deleted_count
