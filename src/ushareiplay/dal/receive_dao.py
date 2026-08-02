from typing import Optional, List
from ushareiplay.models.receive_event import ReceiveEvent
from ushareiplay.dal.user_dao import UserDAO


class ReceiveDao:
    @staticmethod
    async def create(username: str, command: str) -> ReceiveEvent:
        """Create a new receive command rule for a user"""
        user = await UserDAO.get_or_create(username=username)
        return await ReceiveEvent.create(
            user=user,
            command=command
        )

    @staticmethod
    async def get_by_username(username: str) -> List[ReceiveEvent]:
        """Get all receive commands for a user (including canonical account and all aliases)"""
        user_ids = await UserDAO.get_all_associated_user_ids(username=username)
        return await ReceiveEvent.filter(user_id__in=user_ids).order_by('id').prefetch_related('user')

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[ReceiveEvent]:
        """Get receive command by ID"""
        return await ReceiveEvent.get_or_none(id=command_id).prefetch_related('user')

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """Delete a receive command by ID"""
        command = await ReceiveEvent.get_or_none(id=command_id)
        if command:
            await command.delete()
            return True
        return False

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """Delete all receive commands for a user (including canonical account and all aliases)"""
        user_ids = await UserDAO.get_all_associated_user_ids(username=username)
        return await ReceiveEvent.filter(user_id__in=user_ids).delete()


