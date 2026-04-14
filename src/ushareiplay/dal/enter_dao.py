from typing import Optional, List, Tuple
from ushareiplay.models.enter_event import EnterEvent
from ushareiplay.dal.user_dao import UserDAO


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
        effective_user = await UserDAO.get_or_create(username=username)
        return await EnterEvent.filter(user__id=effective_user.id).order_by('id').prefetch_related('user')

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
        effective_user = await UserDAO.get_or_create(username=username)
        deleted_count = await EnterEvent.filter(user__id=effective_user.id).delete()
        return deleted_count
