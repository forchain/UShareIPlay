from typing import List, Optional

from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.models.focus_event import FocusEvent


class FocusEventDao:
    @staticmethod
    async def create(username: str, command: str) -> FocusEvent:
        user = await UserDAO.get_or_create(username=username)
        return await FocusEvent.create(user=user, command=command)

    @staticmethod
    async def get_by_username(username: str) -> List[FocusEvent]:
        effective_user = await UserDAO.get_or_create(username=username)
        return await FocusEvent.filter(user__id=effective_user.id).order_by("id").prefetch_related("user")

    @staticmethod
    async def get_all_ordered() -> List[FocusEvent]:
        """全部专注人数联动命令（按 id），用于人数变化时按配置用户分别入队。"""
        return await FocusEvent.all().order_by("id").prefetch_related("user")

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[FocusEvent]:
        return await FocusEvent.get_or_none(id=command_id).prefetch_related("user")

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        command = await FocusEvent.get_or_none(id=command_id)
        if command:
            await command.delete()
            return True
        return False

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        effective_user = await UserDAO.get_or_create(username=username)
        return await FocusEvent.filter(user__id=effective_user.id).delete()
