from typing import Optional, List, Tuple
from src.models.enter import Enter


class EnterDao:
    @staticmethod
    async def create(username: str, command: str) -> Enter:
        """Create a new enter command"""
        return await Enter.create(
            username=username,
            command=command
        )

    @staticmethod
    async def get_by_username(username: str) -> List[Enter]:
        """Get all enter commands for a user
        Returns:
            List[Enter]: List of enter commands ordered by id
        """
        return await Enter.filter(username=username).order_by('id')

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[Enter]:
        """Get enter command by ID"""
        return await Enter.get_or_none(id=command_id)

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
        deleted_count = await Enter.filter(username=username).delete()
        return deleted_count
