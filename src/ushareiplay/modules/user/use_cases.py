"""用户命名用例：可见昵称解析、别名绑定、等级读写。"""

import logging
from typing import Callable, Optional, Set

from ushareiplay.modules.shared.names import VisibleName
from ushareiplay.modules.shared.roles import RolePolicy
from ushareiplay.modules.user.domain import (
    AliasCycleError,
    MissingCallerError,
    NewLevelNotBelowCallerError,
    TargetNotBelowCallerError,
    User,
    validate_level,
)
from ushareiplay.modules.user.ports import UserRepository


class ResolveVisibleUsername:
    """把 DB 命名域的名字解析成 Soul UI 当前可见的昵称（分身名）。

    在线集合由调用方注入（生产上是 `InfoManager` / `PresenceTracker`），
    保证解析只依赖房间里真正渲染出来的名字。
    """

    def __init__(
        self,
        users: UserRepository,
        is_online: Callable[[str], bool],
        online_users: Callable[[], Set[str]],
        logger: Optional[logging.Logger] = None,
    ):
        self._users = users
        self._is_online = is_online
        self._online_users = online_users
        self._logger = logger or logging.getLogger("ResolveVisibleUsername")

    async def execute(self, username: str) -> VisibleName:
        if not username:
            return VisibleName(username)
        if self._is_online(username):
            return VisibleName(username)
        try:
            identity = await self._users.get_identity_usernames(username)
        except Exception:
            # 解析失败退化为原样返回：调用方还有按身份匹配的兜底路径。
            return VisibleName(username)

        visible = sorted(self._online_users() & identity)
        if not visible:
            return VisibleName(username)
        if len(visible) > 1:
            # 同一身份的多个分身同时在房间里：按稳定顺序取第一个，避免 set 顺序漂移。
            self._logger.info(
                f"多个分身同时在线 {visible}，按稳定顺序使用 {visible[0]} 作为可见昵称"
            )
        return VisibleName(visible[0])


class BindAlias:
    """把别名昵称绑定到 canonical 用户；自引用按环处理。"""

    def __init__(self, users: UserRepository):
        self._users = users

    async def execute(self, alias_username: str, canonical_username: str) -> User:
        alias_user = await self._users.get_or_create_raw(alias_username)
        canonical_user = await self._users.get_or_create(canonical_username)
        if alias_user.id == canonical_user.id:
            raise AliasCycleError(alias_username)
        await self._users.set_canonical(alias_user.id, canonical_user.id)
        return canonical_user


class GetLevel:
    def __init__(self, users: UserRepository):
        self._users = users

    async def execute(self, username: str) -> User:
        return await self._users.get_or_create(username)


class SetLevel:
    """设置等级；普通用户受「目标等级 < 自己」「新等级 < 自己」两条规则约束。"""

    def __init__(self, users: UserRepository, policy: RolePolicy):
        self._users = users
        self._policy = policy

    async def execute(self, caller: str, target_username: str, new_level: int) -> User:
        validate_level(new_level)
        is_operator = self._policy.is_human_operator(caller)
        target = await self._users.get_or_create(target_username)

        if not is_operator:
            if not caller:
                raise MissingCallerError()
            caller_user = await self._users.get_or_create(caller)
            if target.level >= caller_user.level:
                raise TargetNotBelowCallerError(target.level, caller_user.level)
            if new_level >= caller_user.level:
                raise NewLevelNotBelowCallerError(new_level, caller_user.level)

        updated = await self._users.update_level(target.id, new_level)
        return updated
