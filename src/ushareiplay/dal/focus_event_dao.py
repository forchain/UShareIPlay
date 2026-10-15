"""`FocusEventDao` —— 「专注人数联动」命令的向后兼容垫片（#436）。

实现在 `UserEventHookDAO`。这里只保留旧的类名与方法签名。

## `get_all_ordered()` 保留的意义

专注人数联动是唯一需要「不知道触发者是谁、就按配置用户逐个入队」的事件类型：
`UserEventHooks.fire` 在 `changed_users is None`（触发者未知）时回退到这条全量
路径。`UserEventHookDAO.get_all_ordered(FOCUS)` 返回全部用户的行、按 id 升序，
与迁移前一致。

注意与 `changed_users == []`（本次没有用户变更，一条都不发）的区别 —— 三态语义
在 `UserEventHooks.fire` 的文档里，不可合并。

专注人数联动走 **single-id** 口径（只认 canonical 主账号）。旧
`delete_all_by_username` 的 `filter(user__id=…)` + `.delete()` 缺陷由
`UserEventHookDAO` 的外键列过滤修掉，`:focus clear` 恢复可用。
"""

from typing import List, Optional

from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.registry import FOCUS
from ushareiplay.models.focus_event import FocusEvent


class FocusEventDao:
    """`UserEventHookDAO` 在「专注人数联动」事件上的兼容门面。"""

    @staticmethod
    async def create(username: str, command: str) -> FocusEvent:
        """为用户新建一条专注人数联动命令"""
        return await UserEventHookDAO.create(FOCUS, username, command)

    @staticmethod
    async def get_by_username(username: str) -> List[FocusEvent]:
        """取该用户的全部专注人数联动命令（按 id 升序）"""
        return await UserEventHookDAO.get_by_username(FOCUS, username)

    @staticmethod
    async def get_all_ordered() -> List[FocusEvent]:
        """全部用户的专注人数联动命令（按 id 升序），用于人数变化时按配置用户分别入队。"""
        return await UserEventHookDAO.get_all_ordered(FOCUS)

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[FocusEvent]:
        """按 id 取单条专注人数联动命令"""
        return await UserEventHookDAO.get_by_id(FOCUS, command_id)

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """按 id 删单条专注人数联动命令，返回是否真的删掉了"""
        return await UserEventHookDAO.delete_by_id(FOCUS, command_id)

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """清空该用户的全部专注人数联动命令，返回删除条数"""
        return await UserEventHookDAO.delete_all_by_username(FOCUS, username)
