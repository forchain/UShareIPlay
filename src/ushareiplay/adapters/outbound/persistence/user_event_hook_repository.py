"""`UserEventHookRepository` 的 Tortoise 实现。

两张表互不相通是有意保留的：模型各自独立（仓库没有迁移框架，表结构由
`DatabaseManager.init()` 在运行时生成，线上库已在用），跨事件类型复用同一张表会
破坏既有数据。用户解析口径（single-id / alias-group）由领域注册表声明。
"""

from typing import Optional

from ushareiplay.adapters.outbound.persistence.models.enter_event import EnterEvent
from ushareiplay.adapters.outbound.persistence.models.exit_event import ExitEvent
from ushareiplay.adapters.outbound.persistence.models.focus_event import FocusEvent
from ushareiplay.adapters.outbound.persistence.models.receive_event import ReceiveEvent
from ushareiplay.adapters.outbound.persistence.models.return_event import ReturnEvent
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.modules.room.domain import HookCommand
from ushareiplay.modules.room.ports import UserEventHookRepository
from ushareiplay.modules.room.registry import (
    ENTER,
    EXIT,
    FOCUS,
    RECEIVE,
    RETURN,
    Resolution,
    spec_for,
)
from ushareiplay.modules.user.ports import UserRepository

_MODELS = {
    ENTER: EnterEvent,
    EXIT: ExitEvent,
    RETURN: ReturnEvent,
    RECEIVE: ReceiveEvent,
    FOCUS: FocusEvent,
}


def _model_for(event_type: str):
    return _MODELS[event_type]


def _to_domain(row) -> HookCommand:
    return HookCommand(id=row.id, command=row.command, owner=row.user.username)


class TortoiseUserEventHookRepository(UserEventHookRepository):
    def __init__(self, users: Optional[UserRepository] = None):
        self._users = users or TortoiseUserRepository()

    async def _user_filter(self, event_type: str, username: str) -> dict:
        """按该事件类型声明的口径，算出查询用的过滤条件。

        两种口径都用外键列 `user_id` 过滤，而不是 join 写法 `user__id` —— 后者在
        `.delete()` 上会拼出 `near "LEFT": syntax error`。
        """
        spec = spec_for(event_type)
        if spec.resolution is Resolution.ALIAS_GROUP:
            return {"user_id__in": await self._users.get_all_associated_user_ids(username)}
        canonical = await self._users.get_or_create(username)
        return {"user_id": canonical.id}

    async def create(self, event_type: str, username: str, command: str) -> HookCommand:
        model = _model_for(event_type)
        user = await self._users.get_or_create(username)
        row = await model.create(user_id=user.id, command=command)
        return HookCommand(id=row.id, command=row.command, owner=user.username.value)

    async def get_by_username(self, event_type: str, username: str) -> list[HookCommand]:
        model = _model_for(event_type)
        filters = await self._user_filter(event_type, username)
        rows = await model.filter(**filters).order_by("id").prefetch_related("user")
        return [_to_domain(row) for row in rows]

    async def get_all_ordered(self, event_type: str) -> list[HookCommand]:
        model = _model_for(event_type)
        rows = await model.all().order_by("id").prefetch_related("user")
        return [_to_domain(row) for row in rows]

    async def get_by_id(self, event_type: str, command_id: int) -> Optional[HookCommand]:
        model = _model_for(event_type)
        row = await model.get_or_none(id=command_id).prefetch_related("user")
        return None if row is None else _to_domain(row)

    async def delete_by_id(self, event_type: str, command_id: int) -> bool:
        model = _model_for(event_type)
        row = await model.get_or_none(id=command_id)
        if row is None:
            return False
        await row.delete()
        return True

    async def delete_all_by_username(self, event_type: str, username: str) -> int:
        model = _model_for(event_type)
        filters = await self._user_filter(event_type, username)
        return await model.filter(**filters).delete()
