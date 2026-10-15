"""参数化的用户事件钩子持久化层。

原先 5 个 DAO 是逐方法复制的近克隆。这里收敛成一个 `UserEventHookDAO`：模型类与
用户解析口径都来自 `registry.spec_for(event_type)`，因此调用方不再需要知道自己
在处理哪一类事件。

两张表互不相通这一点是有意保留的：模型各自独立（仓库没有迁移框架，表结构由
`DatabaseManager.init()` 在运行时生成，线上库已在用），跨事件类型复用同一张表会
破坏既有数据。
"""

from typing import List, Optional

from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.user_event_hooks.registry import Resolution, spec_for


async def _user_filter(event_type: str, username: str) -> dict:
    """按该事件类型声明的口径，算出查询用的过滤条件。

    这是 alias-group 与 single-id 的唯一分叉点：口径来自注册表，逐事件类型声明，
    不是全局默认。

    两种口径都用外键列 `user_id` 过滤，而不是 join 写法 `user__id` —— 后者在
    `.filter()` 上能生成合法 SQL，交给 `.delete()` 却会拼出 `near "LEFT": syntax
    error`（遗留 DAO 的 `delete_all_by_username` 就踩在这个坑上，只是没有测试覆盖）。
    """
    spec = spec_for(event_type)
    if spec.resolution is Resolution.ALIAS_GROUP:
        return {"user_id__in": await UserDAO.get_all_associated_user_ids(username)}
    canonical = await UserDAO.get_or_create(username=username)
    return {"user_id": canonical.id}


class UserEventHookDAO:
    """跨事件类型的钩子命令 CRUD。事件类型是第一等参数。"""

    @staticmethod
    async def create(event_type: str, username: str, command: str):
        """为用户新建一条该事件类型的钩子命令（写 canonical 主账号）。"""
        spec = spec_for(event_type)
        user = await UserDAO.get_or_create(username=username)
        return await spec.model.create(user=user, command=command)

    @staticmethod
    async def get_by_username(event_type: str, username: str) -> List:
        """该用户在此事件类型下的全部命令，按 id 升序。"""
        spec = spec_for(event_type)
        filters = await _user_filter(event_type, username)
        return await spec.model.filter(**filters).order_by("id").prefetch_related("user")

    @staticmethod
    async def get_all_ordered(event_type: str) -> List:
        """全部用户的命令，按 id 升序。

        专注人数联动在拿不到具体变更用户（`changed_users is None`）时回退到这条
        路径；`changed_users == []` 表示「没有用户变更」，两者不可混用。
        """
        spec = spec_for(event_type)
        return await spec.model.all().order_by("id").prefetch_related("user")

    @staticmethod
    async def get_by_id(event_type: str, command_id: int) -> Optional[object]:
        """按 id 取单条命令。"""
        spec = spec_for(event_type)
        return await spec.model.get_or_none(id=command_id).prefetch_related("user")

    @staticmethod
    async def delete_by_id(event_type: str, command_id: int) -> bool:
        """按 id 删除单条命令，返回是否真的删掉了。"""
        spec = spec_for(event_type)
        command = await spec.model.get_or_none(id=command_id)
        if command:
            await command.delete()
            return True
        return False

    @staticmethod
    async def delete_all_by_username(event_type: str, username: str) -> int:
        """清空该用户在此事件类型下的全部命令，返回删除条数。"""
        spec = spec_for(event_type)
        filters = await _user_filter(event_type, username)
        return await spec.model.filter(**filters).delete()
