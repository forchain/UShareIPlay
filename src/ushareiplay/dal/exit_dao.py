"""`ExitDao` —— 「离开」命令的向后兼容垫片（#436）。

实现在 `UserEventHookDAO`，事件类型与口径来自 `registry.EVENT_HOOK_SPECS`。
这里只保留旧的类名与方法签名。

离开命令走 **single-id** 口径（只认 canonical 主账号）。注意「全分身离线」判定不在
这一层：它在 `gates.py` 里，属于事件触发侧的闸门（`fire(EXIT, ...)` 内部），与
`get_by_username` / `delete_all_by_username` 的查询口径无关。

同 `EnterDao`：旧 `delete_all_by_username` 的 `filter(user__id=…)` + `.delete()`
缺陷由 `UserEventHookDAO` 的外键列过滤修掉，`:exit clear` 恢复可用。
"""

from typing import List, Optional

from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.registry import EXIT
from ushareiplay.models.exit_event import ExitEvent


class ExitDao:
    """`UserEventHookDAO` 在「离开」事件上的兼容门面。"""

    @staticmethod
    async def create(username: str, command: str) -> ExitEvent:
        """为用户新建一条离开命令"""
        return await UserEventHookDAO.create(EXIT, username, command)

    @staticmethod
    async def get_by_username(username: str) -> List[ExitEvent]:
        """取该用户的全部离开命令（按 id 升序）"""
        return await UserEventHookDAO.get_by_username(EXIT, username)

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[ExitEvent]:
        """按 id 取单条离开命令"""
        return await UserEventHookDAO.get_by_id(EXIT, command_id)

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """按 id 删单条离开命令，返回是否真的删掉了"""
        return await UserEventHookDAO.delete_by_id(EXIT, command_id)

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """清空该用户的全部离开命令，返回删除条数"""
        return await UserEventHookDAO.delete_all_by_username(EXIT, username)
