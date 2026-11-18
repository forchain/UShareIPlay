"""用户命名用例：可见昵称解析、别名绑定、等级读写。"""

import asyncio
import logging
import traceback
from typing import Callable, Optional, Set

from ushareiplay.modules.shared.names import VisibleName
from ushareiplay.modules.shared.roles import RolePolicy
from ushareiplay.modules.user.domain import (
    AliasCycleError,
    MemorySettings,
    MissingCallerError,
    NewLevelNotBelowCallerError,
    TargetNotBelowCallerError,
    User,
    validate_level,
)
from ushareiplay.modules.user.ports import (
    ChatLogRepository,
    MemoryDistiller,
    UserMemoryRepository,
    UserRepository,
)


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


class UserMemoryService:
    """ADR-0006 双层记忆用例：记录短期聊天、注入上下文、后台沉淀长期记忆。"""

    def __init__(
        self,
        users: UserRepository,
        memories: UserMemoryRepository,
        chat_logs: ChatLogRepository,
        distiller: MemoryDistiller,
        settings: Optional[MemorySettings] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._users = users
        self._memories = memories
        self._chat_logs = chat_logs
        self._distiller = distiller
        self._settings = settings or MemorySettings()
        self._logger = logger or logging.getLogger("UserMemory")
        self._consolidation_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task = None
        self._running = False
        self._last_user_trigger_time: dict[str, float] = {}

    @property
    def settings(self) -> MemorySettings:
        return self._settings

    @property
    def timeout(self) -> float:
        return self._settings.timeout

    @property
    def min_messages(self) -> int:
        return self._settings.min_messages

    @property
    def min_level_for_long_term(self) -> int:
        return self._settings.min_level_for_long_term

    @property
    def is_enabled(self) -> bool:
        return self._settings.enabled

    async def record_chat(self, username: str, content: str):
        """记录用户 @群主 的发言到短期层。"""
        if not self._settings.enabled or not username or not content:
            return None
        user = await self._users.get_or_create(username)
        return await self._chat_logs.create(user.id, content)

    async def dialogue_context(self, username: str, user_level: int = 0) -> dict:
        """装配对话注入的记忆；低于等级门槛时只给短期聊天。"""
        if not self._settings.enabled or not username:
            return {"directives": [], "profile": "", "short_term_chats": []}

        try:
            user = await self._users.get_or_create(username)
            memory = await self._memories.get(user.id)

            if user_level >= self._settings.min_level_for_long_term:
                directives = list(memory.directives) if memory else []
                profile = memory.profile if memory else ""
            else:
                directives = []
                profile = ""

            since = memory.last_consolidated_at if memory else None
            recent_logs = await self._chat_logs.unconsolidated_logs(
                user.id, since=since, limit=20
            )
            return {
                "directives": directives,
                "profile": profile,
                "short_term_chats": [entry.content for entry in recent_logs],
                "last_consolidated_at": since,
            }
        except Exception:
            self._logger.error(
                f"Error fetching user dialogue context for {username}: {traceback.format_exc()}"
            )
            return {"directives": [], "profile": "", "short_term_chats": []}

    async def start(self):
        """启动后台记忆沉淀 Worker。"""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._logger.info("UserMemory background worker started")

    async def stop(self):
        """停止后台记忆沉淀 Worker。"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._logger.info("UserMemory background worker stopped")

    def schedule_user(self, username: str, force: bool = False):
        """非阻塞调度单用户沉淀检查（带防抖）。"""
        if not self._settings.enabled or not username:
            return

        now = asyncio.get_running_loop().time()
        if not force:
            last_time = self._last_user_trigger_time.get(username, 0)
            if now - last_time < self._settings.debounce_interval:
                self._logger.debug(
                    f"Memory consolidation for {username} skipped due to debouncing"
                )
                return

        self._last_user_trigger_time[username] = now
        self._consolidation_queue.put_nowait({"type": "user", "username": username})
        self._logger.debug(f"Scheduled memory consolidation task for user {username}")

    def schedule_all(self):
        """非阻塞调度全局扫描。"""
        if not self._settings.enabled:
            return
        self._consolidation_queue.put_nowait({"type": "global"})
        self._logger.info("Scheduled global memory consolidation sweep")

    async def _worker_loop(self):
        """低优先级串行后台消费循环（与迁移前节拍一致）。"""
        while self._running:
            try:
                task = await self._consolidation_queue.get()
                if task.get("type") == "user":
                    username = task.get("username")
                    if username:
                        await self.consolidate_user(username)
                elif task.get("type") == "global":
                    await self.consolidate_all_eligible()

                self._consolidation_queue.task_done()
                if self._settings.worker_delay > 0:
                    await asyncio.sleep(self._settings.worker_delay)

            except asyncio.CancelledError:
                break
            except Exception:
                self._logger.error(
                    f"Error in UserMemory worker loop: {traceback.format_exc()}"
                )
                await asyncio.sleep(2.0)

    async def consolidate_user(self, username: str) -> bool:
        """检查并沉淀单个用户的短期记忆；失败不推进游标。"""
        try:
            user = await self._users.get_or_create(username)
            memory = await self._memories.get(user.id)
            since = memory.last_consolidated_at if memory else None

            unconsolidated_count = await self._chat_logs.count_unconsolidated(
                user.id, since=since
            )
            if unconsolidated_count < self._settings.min_messages:
                self._logger.debug(
                    f"User {username} (id={user.id}) unconsolidated logs "
                    f"({unconsolidated_count}) < min_messages "
                    f"({self._settings.min_messages}), skipping."
                )
                return False

            logs = await self._chat_logs.unconsolidated_logs(user.id, since=since)
            if not logs:
                return False

            cutoff_time = logs[-1].created_at
            success, updated_directives, updated_profile = await self._distiller.distill(
                user_name=str(user.username),
                existing_directives=list(memory.directives) if memory else [],
                existing_profile=memory.profile if memory else "",
                new_messages=[entry.content for entry in logs],
            )

            if not success:
                self._logger.warning(
                    f"Memory consolidation failed for user '{user.username}', "
                    "cursor not advanced."
                )
                return False

            await self._memories.update(
                user.id, updated_directives, updated_profile, cutoff_time
            )
            self._logger.info(
                f"Memory successfully consolidated for user '{user.username}' "
                f"(id={user.id}) up to {cutoff_time} ({len(logs)} messages processed)"
            )
            return True

        except Exception:
            self._logger.error(
                f"Error consolidating memory for {username}: {traceback.format_exc()}"
            )
            return False

    async def consolidate_all_eligible(self):
        """全局扫描并沉淀所有达到阈值的活跃用户。"""
        try:
            eligible_users = (
                await self._chat_logs.active_user_ids_with_unconsolidated_logs(
                    min_count=self._settings.min_messages
                )
            )
            self._logger.info(
                f"Global memory sweep found {len(eligible_users)} eligible users "
                f"with >= {self._settings.min_messages} messages"
            )

            for user_id, _count in eligible_users:
                user = await self._users.get_by_id(user_id)
                if user:
                    await self.consolidate_user(str(user.username))
                    if self._settings.worker_delay > 0:
                        await asyncio.sleep(self._settings.worker_delay)

        except Exception:
            self._logger.error(
                f"Error in global memory consolidation sweep: {traceback.format_exc()}"
            )
