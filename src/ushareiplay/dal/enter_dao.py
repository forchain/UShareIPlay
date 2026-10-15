"""`EnterDao` —— 「进入」命令的向后兼容垫片（#436）。

实现在 `UserEventHookDAO`：事件类型是第一等参数，模型类与用户解析口径都来自
`registry.EVENT_HOOK_SPECS`。这里只保留旧的类名与方法签名，把调用转过去。

进入命令走 **single-id** 口径（只认 canonical 主账号），与迁移前逐字一致。

垫片顺带修掉一个真实缺陷：旧实现用 `filter(user__id=…)` 过滤后接 `.delete()`，
而 `user__id` 是 join 写法，Tortoise 会拼出 `near "LEFT": syntax error`。
`UserEventHookDAO` 过滤的是外键列 `user_id`，`:enter clear` 因此第一次真正可用。
"""

from typing import List, Optional

from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.registry import ENTER
from ushareiplay.models.enter_event import EnterEvent


class EnterDao:
    """`UserEventHookDAO` 在「进入」事件上的兼容门面。"""

    @staticmethod
    async def create(username: str, command: str) -> EnterEvent:
        """为用户新建一条进入命令"""
        return await UserEventHookDAO.create(ENTER, username, command)

    @staticmethod
    async def get_by_username(username: str) -> List[EnterEvent]:
        """取该用户的全部进入命令（按 id 升序）"""
        return await UserEventHookDAO.get_by_username(ENTER, username)

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[EnterEvent]:
        """按 id 取单条进入命令"""
        return await UserEventHookDAO.get_by_id(ENTER, command_id)

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """按 id 删单条进入命令，返回是否真的删掉了"""
        return await UserEventHookDAO.delete_by_id(ENTER, command_id)

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """清空该用户的全部进入命令，返回删除条数"""
        return await UserEventHookDAO.delete_all_by_username(ENTER, username)
