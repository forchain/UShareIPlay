"""`ReturnDao` —— 「返回」命令的向后兼容垫片（#436）。

实现在 `UserEventHookDAO`，事件类型与口径来自 `registry.EVENT_HOOK_SPECS`。
这里只保留旧的类名与方法签名。

返回命令走 **single-id** 口径（只认 canonical 主账号）。

同 `EnterDao`：旧 `delete_all_by_username` 的 `filter(user__id=…)` + `.delete()`
缺陷由 `UserEventHookDAO` 的外键列过滤修掉，`:return clear` 恢复可用。
"""

from typing import List, Optional

from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.registry import RETURN
from ushareiplay.models.return_event import ReturnEvent


class ReturnDao:
    """`UserEventHookDAO` 在「返回」事件上的兼容门面。"""

    @staticmethod
    async def create(username: str, command: str) -> ReturnEvent:
        """为用户新建一条返回命令"""
        return await UserEventHookDAO.create(RETURN, username, command)

    @staticmethod
    async def get_by_username(username: str) -> List[ReturnEvent]:
        """取该用户的全部返回命令（按 id 升序）"""
        return await UserEventHookDAO.get_by_username(RETURN, username)

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[ReturnEvent]:
        """按 id 取单条返回命令"""
        return await UserEventHookDAO.get_by_id(RETURN, command_id)

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """按 id 删单条返回命令，返回是否真的删掉了"""
        return await UserEventHookDAO.delete_by_id(RETURN, command_id)

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """清空该用户的全部返回命令，返回删除条数"""
        return await UserEventHookDAO.delete_all_by_username(RETURN, username)
