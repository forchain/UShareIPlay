"""房间用例：房间状态、在线集合与用户事件钩子引擎。

所有协作者（持久化、消息出口、用户仓储、在线集合、记忆沉淀）都从构造函数注入。
跨模块的换房副作用（座位快照、房间档案、播放静音）通过 `on_clear` /
`on_room_change` 回调由组合根注册，模块内部不查找任何单例。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import shlex
import time
import traceback
from typing import Callable, Iterable, List, Optional, Set

from ushareiplay.modules.room.domain import HookCommand, RoomState
from ushareiplay.modules.room.ports import (
    HookCommandSink,
    MemoryConsolidationSink,
    PresenceQuery,
    RoomStateStore,
    UserEventHookRepository,
)
from ushareiplay.modules.room.registry import COMMAND_PREFIXES, EXIT, spec_for
from ushareiplay.modules.user.ports import UserRepository

InfoLog = Callable[[str], None]


class RoomStateService(RoomState):
    """`RoomState` 的用例层：日志、目录、预期房间 ID 持久化与换房副作用。"""

    def __init__(
        self,
        *,
        default_party_id: Optional[str] = None,
        current_party_id: Optional[Callable[[], Optional[str]]] = None,
        catalogue=None,
        store: Optional[RoomStateStore] = None,
        logger: Optional[logging.Logger] = None,
        on_clear: Optional[Iterable[Callable[[], None]]] = None,
        on_room_change: Optional[Iterable[Callable[[], None]]] = None,
    ):
        self._catalogue = catalogue
        self._store = store
        self._logger = logger
        self._on_clear = list(on_clear or ())
        self._on_room_change = list(on_room_change or ())
        super().__init__(
            default_party_id=default_party_id,
            current_party_id=current_party_id,
        )
        self._expected_party_id = store.load_expected_party_id() if store else None

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("ushareiplay.state.room_state")
        return self._logger

    @property
    def recommendation_enabled(self) -> Optional[bool]:
        return self._recommendation_enabled

    @recommendation_enabled.setter
    def recommendation_enabled(self, value: Optional[bool]):
        if self._recommendation_enabled != value:
            self.logger.info(
                f"Recommendation status updated: {self._recommendation_enabled} -> {value}"
            )
        self._recommendation_enabled = value

    @property
    def user_count(self) -> Optional[int]:
        return self._user_count

    @user_count.setter
    def user_count(self, value: int):
        if self._user_count != value:
            self.logger.info(f"User count updated: {self._user_count} -> {value}")
        self._user_count = value

    @property
    def focus_count(self) -> Optional[int]:
        return self._focus_count

    @focus_count.setter
    def focus_count(self, value: int):
        if self._focus_count != value:
            self.logger.info(f"Focus count updated: {self._focus_count} -> {value}")
        self._focus_count = value

    @property
    def room_id(self) -> Optional[str]:
        return self._room_id

    @room_id.setter
    def room_id(self, value: str):
        if self._room_id != value:
            self.logger.info(f"Room ID updated: {self._room_id} -> {value}")
            self._notify_room_change()
        self._room_id = value

    @property
    def expected_party_id(self) -> Optional[str]:
        return self._expected_party_id

    @expected_party_id.setter
    def expected_party_id(self, value: Optional[str]):
        if self._expected_party_id != value:
            self.logger.info(
                f"Expected party ID updated: {self._expected_party_id} -> {value}"
            )
        self._expected_party_id = value
        if self._store is not None:
            self._store.save_expected_party_id(value)

    @property
    def is_guest_room(self) -> bool:
        return super().is_guest_room

    @is_guest_room.setter
    def is_guest_room(self, value: Optional[bool]):
        if self._is_guest_room != value:
            self.logger.info(f"Guest room status updated: {self._is_guest_room} -> {value}")
        self._is_guest_room = value

    def configure_catalogue(self, catalogue) -> None:
        """配置热重载后换用新的命令目录（目录本身不可变）。"""
        self._catalogue = catalogue

    def add_clear_listener(self, listener: Callable[[], None]) -> None:
        """注册「换房 / 退房时随房间作废」的运行期状态。"""
        self._on_clear.append(listener)

    def add_room_change_listener(self, listener: Callable[[], None]) -> None:
        """注册「房间 ID 变更时作废」的跨模块状态。"""
        self._on_room_change.append(listener)

    def is_command_allowed_in_guest_room(self, prefix: str) -> bool:
        if not prefix or self._catalogue is None:
            return False
        return self._catalogue.is_guest_allowed(prefix)

    def clear(self) -> None:
        """清空房间状态，并通知随房间一起作废的跨模块运行期状态。"""
        super().clear()
        for listener in self._on_clear:
            try:
                listener()
            except Exception as e:
                # 换房后座位快照 / 播放静音没清掉会沿用上一间房的数据，不能静默吞掉
                self.logger.error(f"Failed to clear room-scoped state: {e}")
        self._notify_room_change()
        self.logger.info("Cleared room state")

    def _notify_room_change(self) -> None:
        for listener in self._on_room_change:
            try:
                listener()
            except Exception as e:
                # 档案没作废 = 新房间继续沿用旧房名，不能静默吞掉。
                self.logger.error(f"Failed to invalidate room profile on room change: {e}")


class PresenceTracker(PresenceQuery):
    """在线用户集合与进入/离开通知。"""

    def __init__(
        self,
        *,
        logger: Optional[logging.Logger] = None,
        on_user_enter: Optional[Callable[[str], object]] = None,
        on_user_leave: Optional[Callable[[str], object]] = None,
    ):
        self._logger = logger
        self._on_user_enter = on_user_enter
        self._on_user_leave = on_user_leave
        self._online_users: Set[str] = set()
        self._recent_enters: dict[str, float] = {}
        self._recent_returns: dict[str, float] = {}

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("ushareiplay.state.presence_tracker")
        return self._logger

    def update_online_users(self, users: List[str]) -> None:
        try:
            prev_users_set = self._online_users
            new_users_set = set(users)

            users_who_left = set()
            users_who_entered = set()
            if prev_users_set:  # Only check if we have previous data
                users_who_left = prev_users_set - new_users_set
                if users_who_left:
                    for username in users_who_left:
                        self.logger.critical(f"User left: {username}")
                        self._notify(self._on_user_leave, username)

                users_who_entered = new_users_set - prev_users_set
                if users_who_entered:
                    for username in users_who_entered:
                        self.logger.critical(f"User entered: {username}")
                        self._recent_enters[username] = time.time()
                        self._notify(self._on_user_enter, username)

            self._online_users = new_users_set
            self.logger.info(f"Updated online users list: {len(self._online_users)} users")
            self.logger.info(f"Online users: {', '.join(sorted(self._online_users))}")
        except Exception:
            self.logger.error(f"Error updating online users: {traceback.format_exc()}")

    def _notify(self, callback: Optional[Callable[[str], object]], username: str) -> None:
        if callback is None:
            return
        result = callback(username)
        if inspect.isawaitable(result):
            asyncio.create_task(result)

    def was_recently_entered(self, username: str, window_seconds: float = 30.0) -> bool:
        """用户是否在最近 window_seconds 秒内刚进入房间。"""
        now = time.time()
        for name, ts in list(self._recent_enters.items()):
            if now - ts > window_seconds:
                self._recent_enters.pop(name, None)
            elif name == username or name.strip() == username.strip():
                return True
        return False

    def should_trigger_return(self, username: str, debounce_seconds: float = 10.0) -> bool:
        """判断入场消息是否应触发 return（排除全新进入与并发横幅）。"""
        if self._online_users and not self.is_user_online(username):
            return False

        if self.was_recently_entered(username):
            return False

        now = time.time()
        for name, ts in list(self._recent_returns.items()):
            if now - ts > debounce_seconds:
                self._recent_returns.pop(name, None)
            elif name == username or name.strip() == username.strip():
                return False

        return True

    def record_return(self, username: str) -> None:
        self._recent_returns[username] = time.time()

    def is_user_online(self, username: str) -> bool:
        if username in self._online_users:
            return True
        clean_name = username.strip()
        for online in self._online_users:
            if clean_name == online.strip():
                return True
        return False

    def get_online_users(self) -> Set[str]:
        return self._online_users.copy()

    def clear(self) -> None:
        self._online_users.clear()
        self._recent_enters.clear()
        self._recent_returns.clear()
        self.logger.info("Cleared online users list")


def _scalar_ctx(ctx: dict) -> dict:
    """日志里只留标量上下文字段（座位观测那种嵌套数据不进运行时日志）。"""
    return {k: v for k, v in ctx.items() if isinstance(v, (str, int, float, bool))}


class UserEventHooks:
    """用户事件钩子的两个入口：配置 CRUD 与事件触发。"""

    def __init__(
        self,
        *,
        repository: UserEventHookRepository,
        users: UserRepository,
        sink: HookCommandSink,
        presence: PresenceQuery,
        memory: Optional[MemoryConsolidationSink] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._repository = repository
        self._users = users
        self._sink = sink
        self._presence = presence
        self._memory = memory
        self._logger = logger

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("user_event_hooks")
        return self._logger

    def _log_info(self, message: str) -> None:
        self.logger.info(message)

    def _log_error(self, message: str) -> None:
        self.logger.error(message)

    def _log_warning(self, message: str) -> None:
        self.logger.warning(message)

    async def execute_crud(self, event_type: str, username: str, raw_content: str) -> dict:
        """执行一条 `:enter` / `:exit` / `:return` / `:receive` / `:focus` 配置命令。"""
        spec = spec_for(event_type)
        usage = f"缺少参数。使用: {spec.prefix} [add|del|list|clear]"

        try:
            parts = (raw_content or "").split(None, 1)
            if len(parts) < 2:
                return {"error": usage}
            params = shlex.split(parts[1])
        except ValueError:
            return {"error": "参数格式错误，带空格的参数请使用引号包裹"}

        if not params:
            return {"error": usage}

        operation = params[0]

        if operation == "add":
            if len(params) < 2:
                return {"error": f'缺少命令内容。使用: {spec.prefix} add "命令内容"'}

            command = params[1]
            if not command.startswith(COMMAND_PREFIXES):
                return {
                    "error": f"命令必须以命令前缀(:/：或//／)开头，例如 {spec.prefix_example}"
                }

            await self._repository.create(event_type, username, command)
            self._log_info(f"{username} 新增{spec.noun}: {command}")
            return {"message": f"已添加{spec.noun}: {command}"}

        if operation == "del":
            if len(params) < 2:
                return {"error": f"缺少命令ID。使用: {spec.prefix} del <id>"}

            try:
                command_id = int(params[1])
            except ValueError:
                return {"error": "命令ID必须是数字"}

            if await self._repository.delete_by_id(event_type, command_id):
                self._log_info(f"{username} 删除{spec.noun} ID: {command_id}")
                return {"message": f"已删除命令 ID: {command_id}"}
            return {"error": f"未找到命令 ID: {command_id}"}

        if operation == "list":
            commands = await self._repository.get_by_username(event_type, username)
            if not commands:
                return {"message": f"您还没有设置任何{spec.noun}"}

            lines = [f"您的{spec.noun}列表:"]
            lines.extend(f"  [{cmd.id}] {cmd.command}" for cmd in commands)
            return {"message": "\n".join(lines)}

        if operation == "clear":
            count = await self._repository.delete_all_by_username(event_type, username)
            if count > 0:
                self._log_info(f"{username} 清除 {count} 个{spec.noun}")
                return {"message": f"已清除 {count} 个{spec.noun}"}
            return {"message": f"您没有任何{spec.noun}需要清除"}

        return {"error": f"未知操作: {operation}。使用: {spec.prefix} [add|del|list|clear]"}

    async def fire(
        self,
        event_type: str,
        username: Optional[str] = None,
        ctx: Optional[dict] = None,
        *,
        usernames: Optional[Iterable[str]] = None,
    ) -> int:
        """事件发生：把该用户配置的钩子命令投进运行时队列。

        选人分三态，**不可合并**：都为 `None` 回退为该事件类型下所有已配置用户；
        `usernames == []` 一条都不发；给了名单只发这些人的。
        """
        spec = spec_for(event_type)
        ctx = ctx or {}

        try:
            trigger = username
            gated = False
            if event_type == EXIT and username is not None:
                trigger = await self._resolve_exit_target(username)
                if trigger is None:
                    return 0
                gated = True

            if gated:
                targets: Optional[List[str]] = [trigger]
            else:
                targets = self._resolve_targets(username, usernames)

            if targets is not None and not targets:
                return 0

            if targets is None:
                commands = await self._repository.get_all_ordered(event_type)
            else:
                commands = await self._collect_commands(event_type, targets)

            if not commands:
                return 0

            expander = spec.macros
            queued = 0
            for cmd in commands:
                owner = cmd.owner
                text = cmd.command
                if expander is not None:
                    text = await expander(text, owner, ctx, users=self._users)
                # 入队而不是直接执行：队列在 drain 时才展开 `{user_name}` 宏。
                await self._sink.enqueue(
                    text, trigger if trigger is not None else owner
                )
                queued += 1

            scope = "全部用户" if targets is None else ", ".join(targets)
            self._log_info(
                f"{spec.noun}触发 (ctx={_scalar_ctx(ctx) or '无'}), 为 {scope} 入队 {queued} 条命令"
            )
            return queued
        except Exception:
            self._log_error(f"Error in UserEventHooks.fire: {traceback.format_exc()}")
            return 0

    async def _resolve_exit_target(self, username: str) -> Optional[str]:
        """「离开」闸门：全部分身都离线才放行，并以主账号名触发。"""
        all_avatars = await self._users.get_all_avatar_usernames(username)
        still_online = all_avatars & self._presence.get_online_users()

        if still_online:
            self._log_info(
                f"User leave skipped for '{username}': avatars still online: {still_online}"
            )
            return None

        raw_user = await self._users.get_or_create_raw(username)
        canonical_user = await self._users.resolve_canonical(raw_user)
        canonical_username = canonical_user.username.value

        self._log_info(
            f"All avatars offline for '{username}' → triggering user_leave "
            f"as canonical '{canonical_username}'"
        )

        try:
            if self._memory is not None:
                self._memory.schedule_consolidation_user(canonical_username)
        except Exception:
            self._log_warning(
                f"Failed to schedule memory consolidation for user_leave "
                f"'{canonical_username}'"
            )

        return canonical_username

    @staticmethod
    def _resolve_targets(
        username: Optional[str], usernames: Optional[Iterable[str]]
    ) -> Optional[List[str]]:
        """把「单用户 / 名单 / 触发者未知」三态归一成触发者名单。"""
        if username is not None and usernames is not None:
            raise ValueError("fire() 的 username 与 usernames 只能给其中一个")
        if usernames is not None:
            return list(usernames)
        if username is None:
            return None
        if not isinstance(username, str):
            raise TypeError(
                "fire() 的 username 必须是单个用户名；批量触发用 usernames=，"
                "其中 None 表示回退全部已配置用户、[] 表示一个人都不发"
            )
        return [username]

    async def _collect_commands(self, event_type: str, targets: List[str]) -> list[HookCommand]:
        """按名单取命令，按 `cmd.id` 去重（同一主账号的多个分身会解析到同一批行）。"""
        commands = []
        seen_cmd_ids = set()
        for target in targets:
            for cmd in await self._repository.get_by_username(event_type, target):
                if cmd.id not in seen_cmd_ids:
                    seen_cmd_ids.add(cmd.id)
                    commands.append(cmd)
        return commands
