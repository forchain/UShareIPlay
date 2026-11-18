"""房间用例：房间状态、在线集合与用户事件钩子引擎。

所有协作者（持久化、消息出口、用户仓储、在线集合、记忆沉淀）都从构造函数注入。
跨模块的换房副作用（座位快照、房间档案、播放静音）通过 `on_clear` /
`on_room_change` 回调由组合根注册，模块内部不查找任何单例。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import shlex
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Awaitable, Callable, Iterable, List, Optional, Set

from ushareiplay.modules.room.domain import (
    MAX_REDEMPTIONS,
    YELLOW_DUCK_NAME,
    AlreadyRoomAdmin,
    HookCommand,
    NotRoomAdmin,
    PartyLifecycleState,
    RoomAdmins,
    RoomState,
    format_packs,
    is_zero_packs,
    parse_open_pack_args,
    party_create_mode,
)
from ushareiplay.modules.room.ports import (
    ADMIN_ACTION_DISMISS,
    ADMIN_ACTION_INVITE,
    ADMIN_LABEL_DISMISS,
    ADMIN_LABEL_INVITE,
    GIFT_ACTION_USE,
    HookCommandSink,
    LuckPackDriverPort,
    MemoryConsolidationSink,
    OnlineDrawerDriverPort,
    PartyDriverPort,
    PlaybackCacheQueryPort,
    PlaylistQueryPort,
    PresenceQuery,
    RoomStateStore,
    UserEventHookRepository,
)
from ushareiplay.modules.room.registry import COMMAND_PREFIXES, EXIT, spec_for
from ushareiplay.modules.shared.config import ConfigSectionView
from ushareiplay.modules.shared.ports import RoomMessenger
from ushareiplay.modules.user.ports import UserRepository
from ushareiplay.modules.user.use_cases import ResolveVisibleUsername

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
                self._memory.schedule_user(canonical_username)
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


# ---------------------------------------------------------------------------
# 在线用户抽屉（#550 自 managers/online_drawer/manager.py 迁入）
# ---------------------------------------------------------------------------

#: 打不开抽屉时的默认报错文案。调用方可以传 `error_message` 换成自己面向用户的
#: 文本，以免统一入口后改变聊天气泡里的报错。
DEFAULT_OPEN_ERROR = 'Failed to open online users drawer'

#: 抽屉开了但没落定时的默认报错文案。与「打不开」分开表述：前者抽屉多半还开着，
#: 调用方重试有意义；后者连容器都没出现，重试之前应该先确认自己还在房间里。
DEFAULT_SETTLE_ERROR = 'Online users drawer did not settle'

#: 最多翻多少页去找一个人。上限与在线名单抓取同源：别把一次定位变成无上限轮询；
#: 翻满仍找不到就如实回报「未找到」，要不要再来一次由调用方决定。
MAX_SEARCH_SWIPES = 50

#: 两条成功路径的 `action` 文案，会原样进聊天气泡，迁移不是重写。
ACTION_INVITE = 'Invited'
ACTION_DISMISS = 'Dismissed'


class Handover:
    """一次抽屉会话里的**交接**信号。

    会话打开的抽屉默认在退出时收掉。但资料页流程的成功产物恰恰是抽屉之上的那层
    资料卡 —— 卡片与抽屉共用同一个 `ivClose`，此时收尾等于把刚交出去的东西拆掉。
    正文调用 `release()` 把抽屉连同资料卡一起交给调用方，收尾责任随之转移。

    刻意做成一个显式对象，而不是一个布尔开关：开关只能整段会话生效，于是「没找到人
    就中途 return」这类**失败**路径也会被跳过收尾，把抽屉悬在屏幕上。
    """

    def __init__(self):
        self._released = False

    def release(self) -> None:
        """声明「抽屉与资料卡归调用方了」，本会话不再收尾。"""
        self._released = True

    @property
    def released(self) -> bool:
        return self._released


class OnlineDrawer:
    """在线用户抽屉会话的唯一所有者：需要时打开、保证收尾、只关自己开的那次。

    端口、命名域解析器与 UI 独占会话全部由构造方注入；模块内不查找任何单例。

    Args:
        drawer: 抽屉 UI 端口适配器。
        name_resolver: async 命名域解析器，签名 `(str) -> str`。`None` 表示离线装配，
            此时按恒等处理。
        ui_session: 可选，`(reason) -> async context manager` 的 UI 独占锁入口。
            `None` 表示离线装配，退化为不加锁。
        logger: 可选 logger。
    """

    def __init__(
        self,
        *,
        drawer: OnlineDrawerDriverPort,
        name_resolver: Optional[Callable] = None,
        ui_session: Optional[Callable] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._driver = drawer
        self._name_resolver = name_resolver
        self._ui_session_factory = ui_session
        self._logger = logger

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("ushareiplay.modules.room.use_cases")
        return self._logger

    @property
    def driver(self) -> OnlineDrawerDriverPort:
        """抽屉 UI 端口。"""
        return self._driver

    @asynccontextmanager
    async def drawer_session(
        self,
        reason: str = "",
        *,
        error_message: Optional[str] = None,
        settle_error_message: Optional[str] = None,
        handover: Optional[Handover] = None,
    ):
        """抽屉开着的异步上下文：需要时才打开，且只关掉自己打开的那一次。

        Yields:
            error dict（抽屉不可用）或 None（会话已就绪）。
        """
        async with self._ui_session(reason):
            driver = self._require_driver()

            if await driver.is_open():
                # 抽屉不是本会话打开的：不夺取归属，退出后保持原状。
                yield None
                return

            open_error = error_message or DEFAULT_OPEN_ERROR
            result = await driver.open(error_message=open_error)
            if isinstance(result, dict) and 'error' in result:
                self.logger.warning(f"[online_drawer] {reason or 'session'} 打不开在线用户抽屉")
                yield {'error': open_error}
                return

            self.logger.info(f"[online_drawer] {reason or 'session'} 已打开在线用户抽屉")
            if not await driver.wait_for_settle():
                # 抽屉是本会话打开的，必须收尾 —— 否则它会悬在屏幕上等着被下一次
                # 盲按返回误退出房间。
                self.logger.warning(
                    f"[online_drawer] {reason or 'session'} 抽屉打开后未能落定，收尾关闭"
                )
                await self._ensure_closed()
                yield {'error': settle_error_message or error_message or DEFAULT_SETTLE_ERROR}
                return

            try:
                yield None
            except BaseException:
                # 抛异常一律收尾：交接只发生在正文的成功路径上。
                await self._ensure_closed()
                raise
            if handover is None or not handover.released:
                await self._ensure_closed()

    async def close_profile_card(self) -> None:
        """把资料卡连同抽屉收回房间；收不掉只记警告并保持原状，绝不盲按返回。"""
        try:
            async with self._ui_session("online_drawer:close_profile_card"):
                driver = self._require_driver()
                if not await driver.dismiss_profile_card():
                    self.logger.warning(
                        "[online_drawer] 未能通过 ivClose 收起资料卡，保持原状等待下一轮恢复"
                    )
                    return
                self.logger.info("[online_drawer] 资料卡已收起")
        except Exception as e:
            # 收尾失败不能让调用方的正常结果变成异常。
            self.logger.warning(f"[online_drawer] 收起资料卡时出错: {e}")

    async def dismiss_gift_popup(self) -> None:
        """把还盖在资料卡上的送礼弹窗收掉；收不掉只记警告并保持原状。"""
        try:
            async with self._ui_session("online_drawer:dismiss_gift_popup"):
                driver = self._require_driver()
                if not await driver.dismiss_gift_popup():
                    self.logger.warning(
                        "[online_drawer] 未能通过页内关闭键收起送礼弹窗，保持原状等待下一轮恢复"
                    )
                    return
                self.logger.info("[online_drawer] 送礼弹窗已收起")
        except Exception as e:
            self.logger.warning(f"[online_drawer] 收送礼弹窗时出错: {e}")

    async def dismiss_admin_confirm(self) -> None:
        """把盖在资料卡上的房管确认框收掉；收不掉只记警告并保持原状。"""
        try:
            async with self._ui_session("online_drawer:dismiss_admin_confirm"):
                driver = self._require_driver()
                if not await driver.dismiss_admin_confirm():
                    self.logger.warning(
                        "[online_drawer] 未能通过页内关闭键收起房管确认框，保持原状等待下一轮恢复"
                    )
                    return
                self.logger.info("[online_drawer] 房管确认框已收起")
        except Exception as e:
            self.logger.warning(f"[online_drawer] 收房管确认框时出错: {e}")

    @asynccontextmanager
    async def _ui_session(self, reason: str):
        """持有 UI 独占锁；没有注入时退化为不加锁（离线装配）。"""
        if self._ui_session_factory is None:
            yield
            return
        async with self._ui_session_factory(reason or "online_drawer"):
            yield

    async def _ensure_closed(self) -> None:
        """收尾：只走 `ivClose`，点不到就记警告并保持原状。"""
        try:
            driver = self._require_driver()
            if not await driver.is_open():
                return
            if await driver.close():
                self.logger.info("[online_drawer] 在线用户抽屉已关闭")
                return
            self.logger.warning(
                "[online_drawer] 未能通过 ivClose 关闭在线用户抽屉，保持原状等待下一轮恢复"
            )
        except Exception as e:
            # 抽屉还开着是「难看」，抛出去是「任务失败」，后者更糟。
            self.logger.warning(f"[online_drawer] 关闭在线用户抽屉时出错: {e}")

    @asynccontextmanager
    async def card_session(self, reason: str):
        """交接之后、收尾之前的「卡片独占」，把住 UI 锁。"""
        async with self._ui_session(reason):
            yield

    async def find_member_in_drawer(self, visible_name: str) -> bool:
        """在抽屉里一页一页找某个 UI 可见昵称。

        翻到哪一页、翻够几页、什么时候如实回报「未找到」都是**会话的决策**，端口只
        负责如实回答「此刻屏幕上有哪些行」。
        """
        driver = self._require_driver()
        for _ in range(MAX_SEARCH_SWIPES + 1):
            if await driver.find_member_row(visible_name) is not None:
                return True

            if await driver.is_at_end():
                self.logger.info("Detected no_more_data, stop searching online users.")
                return False

            if not await driver.scroll_container():
                self.logger.warning("Swipe failed, stop searching online users.")
                return False

        self.logger.warning(f"Reached max_swipes, stop searching for {visible_name}.")
        return False

    async def resolve_visible_username(self, username: str) -> str:
        """把任意命名域的名字解析成 Soul UI 上可见的昵称（分身名）。

        **没有注入解析器时（离线装配、单元测试）原样返回**。
        """
        if self._name_resolver is None:
            return username
        return await self._name_resolver(username)

    def _require_driver(self) -> OnlineDrawerDriverPort:
        if self._driver is None:
            # 组合根漏了接线：显式失败，而不是悄悄退回裸 Appium 操作。
            raise RuntimeError(
                "OnlineDrawer drawer actions require an OnlineDrawerDriverPort adapter; "
                "wire it at the composition root."
            )
        return self._driver


class ManageAdmin:
    """房管授予与解除的用例：开抽屉 -> 找人 -> 资料卡 -> 开关 -> 确认 -> 记账。

    既有的幂等失败（已经是/还不是房管）在这里落成命名异常；聊天命令只负责把异常
    翻成原话。
    """

    def __init__(
        self,
        *,
        drawer: OnlineDrawer,
        admins: RoomAdmins,
        logger: Optional[logging.Logger] = None,
    ):
        self._drawer = drawer
        self._admins = admins
        self._logger = logger

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("ushareiplay.modules.room.use_cases")
        return self._logger

    def is_room_admin(self, username: str) -> bool:
        return self._admins.is_admin(username)

    def get_room_admins(self) -> set[str]:
        return self._admins.all()

    def add_room_admin(self, username: str) -> None:
        self._admins.add(username)

    def remove_room_admin(self, username: str) -> None:
        self._admins.remove(username)

    def clear_room_admins(self) -> None:
        self._admins.clear()

    async def manage_admin(self, enable: bool, target_nickname: str) -> dict:
        """在在线列表中打开目标用户资料页，再执行邀请/解除管理。

        Args:
            enable: True 邀请为管理员，False 解除管理员。
            target_nickname: canonical 名或 UI 可见昵称；解析在抽屉会话里完成。

        Raises:
            AlreadyRoomAdmin / NotRoomAdmin: 名单规则失败。
        """
        drawer = self._drawer
        driver = drawer.driver
        handover = Handover()

        async with drawer.drawer_session(
            reason=f"admin:{target_nickname}",
            error_message='Failed to open online users list',
            settle_error_message='Failed to find online users container',
            handover=handover,
        ) as open_error:
            if open_error:
                return {'error': open_error['error'], 'user': target_nickname}

            # 先解析命名域再进 UI 搜索：抽屉里只有可见昵称能定位到人。
            visible_name = await self._resolve_visible_name(drawer, target_nickname)

            if not await drawer.find_member_in_drawer(visible_name):
                self.logger.warning(f"未找到用户 {visible_name}")
                return {
                    'error': 'User not found in online users list',
                    'user': visible_name,
                }

            if not await driver.open_member_profile(visible_name):
                self.logger.error(f"Failed to click user element: {visible_name}")
                return {'error': 'Failed to click user element', 'user': visible_name}

            self.logger.info(f"Clicked user element for {visible_name}")
            # 卡片已经交到自己手里：接下来每一条路径都要自己收。
            handover.release()
            try:
                return await self._toggle_on_card(driver, enable, visible_name)
            finally:
                await self._close_admin_overlays()

    async def _resolve_visible_name(self, drawer: OnlineDrawer, nickname: str) -> str:
        """把 canonical 名解析成房间里可见的分身名；解析不了就按原名找。"""
        try:
            return await drawer.resolve_visible_username(nickname)
        except Exception:
            # 解析器是别处的单例，让它的一次抖动把整条房管流程变成硬失败并不划算。
            return nickname

    async def _toggle_on_card(self, driver, enable: bool, target_nickname: str) -> dict:
        """已经在资料卡上：读开关文案 -> 判幂等 -> 点开关 -> 点确认。"""
        label = await driver.read_admin_invite_label()
        if label is None:
            return {'error': 'Failed to find manager invite button', 'user': target_nickname}

        if enable:
            if label == ADMIN_LABEL_DISMISS:
                # 屏幕说是房管：先把抄写修正，再如实回报「已经」。
                self._admins.add(target_nickname)
                raise AlreadyRoomAdmin(target_nickname)
            action = ACTION_INVITE
            driver_action = ADMIN_ACTION_INVITE
        else:
            if label == ADMIN_LABEL_INVITE:
                self._admins.remove(target_nickname)
                raise NotRoomAdmin(target_nickname)
            action = ACTION_DISMISS
            driver_action = ADMIN_ACTION_DISMISS

        # 点开关失败只记警告不改道：真正的判据是下一步确认框有没有出来。
        if not await driver.click_admin_invite():
            self.logger.warning("点击管理邀请按钮失败")
        self.logger.info("Clicked manager invite button")

        if not await driver.confirm_admin_action(driver_action):
            self.logger.error(
                f"Failed to find {action} confirmation button for {target_nickname}"
            )
            return {'error': f'Failed to find {action} confirmation button', 'user': target_nickname}

        self.logger.info(f"Clicked {action} confirmation button")

        if enable:
            self._admins.add(target_nickname)
        else:
            self._admins.remove(target_nickname)

        return {'user': target_nickname, 'action': action}

    async def _close_admin_overlays(self) -> None:
        """按相反顺序分层收：先收确认框，再收资料卡连同抽屉。"""
        await self._drawer.dismiss_admin_confirm()
        await self._drawer.close_profile_card()


# ---------------------------------------------------------------------------
# 派对生命周期、只读 InfoManager、送礼/私聊资料卡、福袋（#552）
# ---------------------------------------------------------------------------


class PartyService:
    """派对生命周期用例：建房、退房、切房、房间核对与定时自动重启。"""

    def __init__(
        self,
        *,
        driver: PartyDriverPort,
        room_state: RoomStateService,
        lifecycle: Optional[PartyLifecycleState] = None,
        config: Optional[ConfigSectionView] = None,
        messenger: Optional[RoomMessenger] = None,
        on_sync_profile: Optional[Callable[[], object]] = None,
        on_after_create_notice: Optional[Callable[[], Awaitable[dict]]] = None,
        on_after_create_seat: Optional[Callable[[], Awaitable[dict]]] = None,
        on_after_create_automation: Optional[Callable[[], Awaitable[None]]] = None,
        on_memory_consolidate: Optional[Callable[[], None]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._driver = driver
        self._room_state = room_state
        self._lifecycle = lifecycle if lifecycle is not None else PartyLifecycleState()
        self._config = config
        self._messenger = messenger
        self._on_sync_profile = on_sync_profile
        self._on_after_create_notice = on_after_create_notice
        self._on_after_create_seat = on_after_create_seat
        self._on_after_create_automation = on_after_create_automation
        self._on_memory_consolidate = on_memory_consolidate
        self._logger = logger

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("PartyManager")
        return self._logger

    @property
    def lifecycle(self) -> PartyLifecycleState:
        return self._lifecycle

    @property
    def init_time(self) -> Optional[datetime]:
        return self._lifecycle.init_time

    def _config_value(self, key: str, default=None):
        if self._config is None:
            return default
        return self._config.value(key, default)

    def initialize_party(self) -> None:
        """初始化派对管理器计时。"""
        trigger_minutes = self._config_value('party_restart_minutes', 720)
        if self._lifecycle.initialize(trigger_minutes=trigger_minutes):
            self.logger.info(f"派对管理器已初始化，触发时间: {self._lifecycle.trigger_minutes}分钟")

    def reset_party_time(self) -> None:
        """重置派对创建时间。"""
        current_time = self._lifecycle.reset_time()
        self.logger.info(f"Party creation time reset to: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

    def get_party_user_count(self) -> int:
        """获取当前派对人数，失败或未初始化返回 -1。"""
        try:
            user_count = self._room_state.user_count
            return -1 if user_count is None else user_count
        except Exception:
            self.logger.error(f"获取派对人数时出错: {traceback.format_exc()}")
            return -1

    def is_party_active(self) -> bool:
        """检查派对是否处于活跃状态。"""
        try:
            return self.get_party_user_count() > 0
        except Exception:
            self.logger.error(f"检查派对状态时出错: {traceback.format_exc()}")
            return False

    def update(self) -> None:
        """检查并自动管理派对。"""
        try:
            if self._room_state.is_guest_room:
                return

            if self._lifecycle.init_time is None:
                self.initialize_party()
                return

            current_time = datetime.now()
            user_count = self.get_party_user_count()
            if not self._lifecycle.should_auto_restart(
                current_time,
                user_count=user_count,
                is_guest_room=self._room_state.is_guest_room,
            ):
                return

            minutes_since_init = (current_time - self._lifecycle.init_time).total_seconds() / 60
            self.logger.info("检测到只有1人在派对中，准备重启派对...")
            self.logger.info(
                f"运行时间: {minutes_since_init:.1f}分钟, 当前时间: {current_time.hour}点"
            )

            end_success = self.end_party()
            # update() 每条聊天消息都会跑到这里，失败后立即重试会反复打断 UI，
            # 所以一次/天同时约束失败重试，不只是成功。
            self._lifecycle.mark_auto_ended(current_time.date())
            if isinstance(end_success, dict) and 'error' not in end_success:
                self.logger.info("派对关闭成功")
                self.reset_party_time()
                self.logger.info("已重置重启功能状态，重新开始计时")
            else:
                self.logger.error(f"派对关闭失败: {end_success}")
        except Exception:
            self.logger.error(f"Error in party management update: {traceback.format_exc()}")

    def end_party(self) -> dict:
        """结束派对（供命令与自动重启调用）。"""
        try:
            if self._messenger is not None:
                try:
                    self._messenger.send_screen_message('Ending party')
                except Exception as msg_e:
                    self.logger.debug(f"Failed to send screen message: {msg_e}")

            result = self._driver.end_party_ui()
            if 'error' in result:
                return result

            self._room_state.expected_party_id = None
            self._room_state.clear()
            self._driver.set_party_id(None)

            if self._on_memory_consolidate is not None:
                try:
                    self._on_memory_consolidate()
                except Exception:
                    self.logger.warning("Failed to schedule memory consolidation on end_party")

            return {'success': 'Party ended'}
        except Exception:
            self.logger.error(f"Error processing end command: {traceback.format_exc()}")
            return {'error': 'Failed to end party'}

    async def verify_current_room(self, room_id: str, *, source: str = "runtime") -> bool:
        """核对当前所在房间是否与预期一致；不一致则退房重建。"""
        if not room_id:
            return False

        expected_id = self._room_state.get_expected_party_id()

        if expected_id and room_id != expected_id:
            if self._room_state.adopt_host_room(room_id):
                self.logger.info(
                    f"Owner transfer detected at {source}: adopted room {room_id} as own host room"
                )
                self._driver.set_party_id(room_id)
                return False

            self.logger.warning(
                f"Room ID mismatch detected at {source}: current={room_id}, expected={expected_id}. "
                f"Exiting room and recreating party..."
            )
            await self.leave_and_recreate_party()
            return True

        is_new_room = self._room_state.room_id != room_id
        self._room_state.room_id = room_id
        self._driver.set_party_id(room_id)
        if source == "startup" or is_new_room:
            self.logger.info(f"Room verified at {source}: {room_id}")
        return False

    async def invite_user(self, requester_nickname: str, party_id: str) -> dict:
        """邀请当前账号加入指定派对（切房前先校验目标房间是否开启）。"""
        try:
            self._driver.minimize_room()

            if not self._driver.navigate_to_hall_entry():
                self.logger.debug("navigate_to_hall_entry returned False before search")

            if not self._driver.search_party(party_id):
                self._driver.restore_current_party()
                return {
                    'error': 'Failed to find search entry or search box',
                    'party_id': party_id,
                }

            if not self._driver.is_target_party_online():
                self.logger.warning(
                    f"Target party {party_id} is closed or not found, restoring previous party"
                )
                self._driver.restore_current_party()
                return {
                    'error': f'Party {party_id} is closed or not found',
                    'party_id': party_id,
                }

            self.logger.info(f"Target party {party_id} is open. Restoring and closing current party...")
            self._driver.restore_current_party()
            self.end_party()

            self.logger.info(
                f"Current party closed. Navigating to hall to enter target party {party_id}..."
            )
            self._driver.navigate_to_hall_entry()

            if not self._driver.search_party(party_id):
                return {
                    'error': f'Failed to search party {party_id} after closing previous room',
                    'party_id': party_id,
                }

            if not self._driver.enter_searched_party():
                return {
                    'error': f'Failed to locate room card for party {party_id}',
                    'party_id': party_id,
                }

            self._driver.set_party_id(party_id)
            self._room_state.expected_party_id = party_id
            self._room_state.room_id = party_id
            return {'party_id': party_id, 'user': requester_nickname}
        except Exception as e:
            self.logger.error(f"Error inviting to party: {traceback.format_exc()}")
            self._driver.restore_current_party()
            return {'error': str(e), 'party_id': party_id}

    async def leave_and_recreate_party(self) -> bool:
        """退出意外房间并重建主房间。"""
        self.logger.warning(
            "Leaving unexpected/unauthorized room and returning to home to recreate party..."
        )
        try:
            self.end_party()
        except Exception as e:
            self.logger.warning(f"Error while leaving unexpected room: {e}")

        self._room_state.expected_party_id = None
        self._room_state.clear()
        self._driver.set_party_id(None)

        return await self.join_party()

    async def join_party(self) -> bool:
        """从首页/大厅返回或创建派对。"""
        try:
            if self._driver.click_visible_party_back():
                self._sync_profile_from_ui()
                return True

            if not self._driver.enter_party_hall_from_home():
                return False

            self._room_state.clear()
            self._driver.set_party_id(None)

            default_party_id = self._config_value('default_party_id')
            target_party_id = default_party_id or self._driver.get_party_id()
            if self._driver.try_enter_existing_party(target_party_id):
                self._sync_profile_from_ui()
                return True

            raw_mode = self._config_value('party_create_mode', 'new_party_entry')
            mode = party_create_mode(raw_mode)
            if raw_mode not in ('new_party_entry', 'restore_party'):
                self.logger.warning(f"未知 party_create_mode={raw_mode}，回退 new_party_entry")

            recommendation_enabled = bool(
                self._config_value('create_party_recommendation', True)
            )
            change_party_type = bool(self._config_value('change_party_type', False))
            target_type_key = self._config_value('target_party_type_element', 'party_type_singing')

            created, actual_rec = self._driver.create_party_flow(
                mode=mode,
                recommendation_enabled=recommendation_enabled,
                change_party_type=change_party_type,
                target_party_type_element=target_type_key,
            )
            if not created:
                return False
            if actual_rec is not None:
                self._room_state.recommendation_enabled = actual_rec
            await self._after_party_created()
            return True
        except Exception as e:
            self.logger.debug(f"检测首页时出错: {str(e)}")
            return False

    def _sync_profile_from_ui(self) -> None:
        if self._on_sync_profile is not None:
            self._on_sync_profile()

    async def _after_party_created(self) -> None:
        self.reset_party_time()
        self._room_state.promote_to_host_room(self._driver.get_party_id())
        self._sync_profile_from_ui()
        self.logger.info(
            f"Party recommendation configured during creation: {self._room_state.recommendation_enabled}"
        )

        self.logger.info("派对创建成功，准备设置默认notice")
        if self._on_after_create_notice is not None:
            result = await self._on_after_create_notice()
            if 'success' in result:
                self.logger.info("默认notice设置成功")
            else:
                self.logger.warning(f"默认notice设置失败: {result.get('error', 'Unknown error')}")

        self.logger.info("Attempting to seat owner after party creation")
        if self._on_after_create_seat is not None:
            result = await self._on_after_create_seat()
            if 'success' in result:
                self.logger.info("Owner successfully seated")
            else:
                self.logger.warning(f"Failed to seat owner: {result.get('error', 'Unknown error')}")

        if self._on_after_create_automation is not None:
            await self._on_after_create_automation()
        else:
            self.logger.warning("post_party_create_automation not initialized; skip auto commands")

        if self._on_memory_consolidate is not None:
            try:
                self._on_memory_consolidate()
            except Exception:
                self.logger.warning(
                    "Failed to schedule memory consolidation on _after_party_created"
                )


class InfoManager:
    """只读信息门面（ADR-0004）：统一查询房间状态、在线用户、歌单与播放缓存。

    严禁暴露任何写方法或状态 setter。
    """

    def __init__(
        self,
        *,
        room_state: RoomState,
        presence: PresenceQuery,
        room_admins: Optional[RoomAdmins] = None,
        playlist: Optional[PlaylistQueryPort] = None,
        playback_cache: Optional[PlaybackCacheQueryPort] = None,
        party_lifecycle: Optional[PartyLifecycleState] = None,
        users: Optional[UserRepository] = None,
        name_resolver: Optional[Callable[[str], Awaitable[str]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._room_state = room_state
        self._presence = presence
        self._room_admins = room_admins
        self._playlist = playlist
        self._playback_cache = playback_cache
        self._party_lifecycle = party_lifecycle
        self._users = users
        self._name_resolver = name_resolver
        self._logger = logger

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("InfoManager")
        return self._logger

    # ------------------------------------------------------------------
    # Playlist / Player 状态（只读门面）
    # ------------------------------------------------------------------
    @property
    def player_name(self) -> str:
        if self._playlist is None:
            return "未知"
        return self._playlist.player_name

    @property
    def current_playlist_name(self) -> str:
        if self._playlist is None:
            return ""
        return self._playlist.current_playlist_name

    @property
    def pending_next_count(self) -> int:
        if self._playlist is None:
            return 0
        return self._playlist.pending_next_count

    @property
    def next_queue_contributors(self) -> Set[str]:
        if self._playlist is None:
            return set()
        return self._playlist.next_queue_contributors

    def get_playlist_info(self) -> Optional[dict]:
        if self._playlist is None:
            return None
        return self._playlist.get_playlist_info()

    # ------------------------------------------------------------------
    # 在线用户与房管（只读）
    # ------------------------------------------------------------------
    def is_user_online(self, username: str) -> bool:
        return self._presence.is_user_online(username)

    def get_online_users(self) -> Set[str]:
        return self._presence.get_online_users()

    def get_room_admins(self) -> Set[str]:
        return self._room_admins.all() if self._room_admins is not None else set()

    async def is_user_or_avatar_online(self, username: str) -> bool:
        if not username:
            return False
        if self.is_user_online(username):
            return True
        if self._users is None:
            return False
        try:
            all_avatars = await self._users.get_all_avatar_usernames(username)
            return bool(all_avatars & self.get_online_users())
        except Exception:
            return self.is_user_online(username)

    async def resolve_visible_username(self, username: str) -> str:
        if self._name_resolver is not None:
            return str(await self._name_resolver(username))
        if self._users is None:
            return username
        use_case = ResolveVisibleUsername(
            users=self._users,
            is_online=self.is_user_online,
            online_users=self.get_online_users,
            logger=self.logger,
        )
        return str(await use_case.execute(username))

    # ------------------------------------------------------------------
    # 房间状态（只读）
    # ------------------------------------------------------------------
    @property
    def user_count(self) -> Optional[int]:
        return self._room_state.user_count

    @property
    def focus_count(self) -> Optional[int]:
        return self._room_state.focus_count

    @property
    def room_id(self) -> Optional[str]:
        return self._room_state.room_id

    @property
    def recommendation_enabled(self) -> Optional[bool]:
        return self._room_state.recommendation_enabled

    # ------------------------------------------------------------------
    # 派对时长 / 播放缓存（只读）
    # ------------------------------------------------------------------
    def get_party_duration_info(self) -> Optional[str]:
        if self._party_lifecycle is None:
            return None
        try:
            return self._party_lifecycle.format_duration_info()
        except Exception:
            self.logger.error(f"Error getting party duration info: {traceback.format_exc()}")
            return None

    def get_playback_info_cache(self) -> Optional[dict]:
        if self._playback_cache is None:
            return None
        return self._playback_cache.get_playback_info_cache()

    def ensure_cached_release_date(self) -> Optional[dict]:
        if self._playback_cache is None:
            return None
        return self._playback_cache.ensure_cached_release_date()


OPEN_DRAWER_ERROR = 'Failed to open online users list'
FIND_DRAWER_ERROR = 'Failed to find online users container'


class UserProfileActions:
    """资料卡送礼与私聊用例：经由 OnlineDrawer 会话编排。"""

    def __init__(
        self,
        *,
        drawer: OnlineDrawer,
        logger: Optional[logging.Logger] = None,
    ):
        self._drawer = drawer
        self._logger = logger

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("UserManager")
        return self._logger

    @property
    def drawer(self) -> OnlineDrawer:
        return self._drawer

    async def open_user_profile(self, nickname: str) -> dict:
        return await self.open_user_profile_from_online_list(nickname)

    async def open_user_profile_from_online_list(self, nickname: str) -> dict:
        drawer = self._drawer
        driver = drawer.driver
        handover = Handover()

        async with drawer.drawer_session(
            reason=f"user:open_profile:{nickname}",
            error_message=OPEN_DRAWER_ERROR,
            settle_error_message=FIND_DRAWER_ERROR,
            handover=handover,
        ) as open_error:
            if open_error:
                return {'error': open_error['error'], 'user': nickname}

            visible_name = await drawer.resolve_visible_username(nickname)
            if not await drawer.find_member_in_drawer(visible_name):
                self.logger.warning(f"未找到用户 {visible_name}")
                return {
                    'error': 'User not found in online users list',
                    'user': nickname,
                }

            if not await driver.open_member_profile(visible_name):
                self.logger.error(f"Failed to click user element: {visible_name}")
                return {'error': 'Failed to click user element', 'user': nickname}

            self.logger.info(f"Clicked user element for {visible_name}")
            handover.release()
            return {'user': nickname}

    async def close_user_profile(self) -> None:
        await self._drawer.close_profile_card()

    async def send_gift(self, nickname: str) -> dict:
        open_result = await self.open_user_profile(nickname)
        if 'error' in open_result:
            return open_result

        async with self._drawer.card_session(f"user:gift:{nickname}"):
            try:
                return await self._gift_on_card(self._drawer.driver)
            finally:
                await self._close_gift_overlays()

    async def _gift_on_card(self, driver: OnlineDrawerDriverPort) -> dict:
        if not await driver.open_gift_entry():
            self.logger.info("未找到送礼物按钮")
            return {'error': '未找到送礼物入口'}

        self.logger.info("已点击送礼物")

        action = await driver.gift_popup_action()
        if action is None:
            self.logger.info("送礼界面未出现或超时")
            return {'error': '送礼界面未出现'}

        gift_name = await driver.read_gift_item_name()
        if gift_name is None:
            self.logger.warning('Failed to find gift')
            return {'error': 'Failed to find gift'}

        if gift_name.strip() == YELLOW_DUCK_NAME:
            await driver.click_gift_item()
            self.logger.info(f"已点击{YELLOW_DUCK_NAME}，送出后关闭在线列表")
            return {'success': f'{gift_name} 送你啦'}

        soul_power = await driver.read_gift_soul_power()
        soul_points = soul_power if soul_power is not None else '0'

        if not await driver.click_gift_action():
            self.logger.warning("点击赠送/使用按钮失败")

        self.logger.info(f"已点击赠送, gift_name: {gift_name} soul_points: {soul_points}")

        if action == GIFT_ACTION_USE:
            if not await driver.confirm_gift_use():
                self.logger.warning("未找到确认使用按钮")
                return {'error': '未找到确认使用按钮'}
            self.logger.info("已点击确认使用")

        return {'success': f'{gift_name} 送你啦'}

    async def _close_gift_overlays(self) -> None:
        await self._drawer.dismiss_gift_popup()
        await self.close_user_profile()

    async def send_private_message_to_user(self, nickname: str, message: str) -> bool:
        try:
            drawer = self._drawer
            driver = drawer.driver
            await driver.switch_to_app()
            handover = Handover()

            async with drawer.drawer_session(
                reason=f"user:private_message:{nickname}",
                error_message=OPEN_DRAWER_ERROR,
                settle_error_message=FIND_DRAWER_ERROR,
                handover=handover,
            ) as open_error:
                if open_error:
                    self.logger.warning(
                        f"打开用户资料页失败: {nickname}, error={open_error['error']}"
                    )
                    return False

                visible_name = await drawer.resolve_visible_username(nickname)
                if not await drawer.find_member_in_drawer(visible_name):
                    self.logger.warning(f"未找到用户 {visible_name}")
                    return False
                if not await driver.open_member_profile(visible_name):
                    self.logger.warning(f"打开用户资料页失败: {nickname}")
                    return False

                handover.release()
                return await self._private_message_on_card(driver, nickname, message)
        except Exception as e:
            self.logger.error(f"私聊发送失败: {nickname}, error={e}")
            return False

    async def _private_message_on_card(
        self, driver: OnlineDrawerDriverPort, nickname: str, message: str
    ) -> bool:
        sent = False
        try:
            if not await driver.open_member_home():
                self.logger.warning(f"未找到头像入口: {nickname}")
                return False
            if not await driver.open_private_chat_page():
                self.logger.warning(f"未找到私聊按钮: {nickname}")
                return False
            if not await driver.type_private_message(message):
                self.logger.warning(f"未找到私聊输入框: {nickname}")
                return False
            if not await driver.submit_private_message():
                self.logger.warning(f"未找到私聊发送按钮: {nickname}")
                return False
            sent = True
        except Exception as e:
            self.logger.error(f"私聊发送失败: {nickname}, error={e}")
        finally:
            if not await driver.return_to_room():
                self.logger.warning(f"未找到返回聊天室入口: {nickname}")
                sent = False
        return sent


class LuckPackService:
    """福袋列表、开启、自动开包与热力兑换用例。"""

    def __init__(
        self,
        *,
        driver: LuckPackDriverPort,
        room_state: Optional[RoomState] = None,
        verify_only: Optional[Callable[[], bool]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._driver = driver
        self._room_state = room_state
        self._verify_only = verify_only or (lambda: os.getenv("VERIFY_ONLY_PACK") == "1")
        self._logger = logger
        self.auto_mode = False
        self.previous_count = 0

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("LuckPackService")
        return self._logger

    def update(self) -> None:
        """检查在线人数变化，人数 > 5 时自动开福袋。"""
        try:
            if self._room_state is None:
                return
            count = self._room_state.user_count
            if count is None:
                return
            if count != self.previous_count:
                self.previous_count = count
                if count > 5:
                    self.auto_mode = True
                    self.open_luck_pack(user_count=count)
        except Exception:
            self.logger.error(f"Error in pack update: {traceback.format_exc()}")

    def list_packs(self) -> dict:
        """打开福袋抽屉，扫描当前拥有的福袋列表。"""
        if not self._driver.open_pack_drawer():
            return {'error': '未找到福袋入口'}
        try:
            tab_text = self._driver.wait_pack_tab()
            if tab_text is None:
                return {'error': '福袋抽屉未打开'}
            self.logger.info("已打开福袋抽屉")
            if is_zero_packs(tab_text):
                packs = []
            else:
                if not self._driver.wait_pack_list():
                    return {'error': '未找到福袋列表'}
                packs = self._driver.scan_packs()
        except Exception:
            self.logger.error(f"Error listing packs: {traceback.format_exc()}")
            return {'error': 'Failed to list luck packs'}
        finally:
            self._driver.close_pack_drawer()
        if not packs:
            return {'message': '当前没有福袋'}
        return {'message': format_packs(packs)}

    def open_pack(self, parameters: list[str]) -> dict:
        """开启福袋。参数：[level] [countdown]；level 省略时选等级最小的福袋。"""
        level, countdown, error = parse_open_pack_args(parameters)
        if error:
            return {'message': error}
        if not self._driver.open_pack_drawer():
            return {'error': '未找到福袋入口'}
        used = False
        try:
            tab_text = self._driver.wait_pack_tab()
            if tab_text is None:
                return {'error': '福袋抽屉未打开'}
            self.logger.info("已打开福袋抽屉")
            if is_zero_packs(tab_text):
                return {'error': f'未找到{level}级福袋' if level else '未找到可用的福袋'}
            if not self._driver.wait_pack_list():
                return {'error': '未找到福袋列表'}
            target_level = self._driver.locate_pack(level)
            if target_level is None:
                return {'error': f'未找到{level}级福袋' if level else '未找到可用的福袋'}
            changed = self._driver.sync_countdown(countdown)
            if changed is None:
                return {'error': '倒计时设置失败'}
            if changed:
                if not self._driver.wait_pack_list():
                    return {'error': '未找到福袋列表'}
                target_level = self._driver.locate_pack(level)
                if target_level is None:
                    return {'error': f'未找到{level}级福袋' if level else '未找到可用的福袋'}
            if not self._driver.click_pack(target_level):
                return {'error': f'未找到{level}级福袋' if level else '未找到可用的福袋'}
            if not self._driver.wait_use_pack_clickable():
                return {'error': '福袋未选中，使用按钮不可用'}
            if self._verify_only():
                self.logger.info(
                    f"[VERIFY_ONLY] 已检测到使用按钮可用（目标 {target_level} 级福袋），按验证要求不点击开启并安全关闭抽屉"
                )
                return {'message': f'[验证成功] 已检测到{target_level}级福袋使用按钮，已安全关闭'}
            self._driver.click_use_pack()
            used = True
            self.logger.info(f'已开启 {target_level} 级福袋')
            return {'message': f'已开启{target_level}级福袋'}
        except Exception:
            self.logger.error(f"Error opening pack: {traceback.format_exc()}")
            return {'error': 'Failed to open luck pack'}
        finally:
            if not used:
                self._driver.close_pack_drawer()

    def open_luck_pack(self, user_count: Optional[int] = None) -> dict:
        """主循环自动/快捷开福袋流程。"""
        return self._driver.auto_open_luck_pack(user_count, self.auto_mode)

    def redeem_heat(self) -> dict:
        """用热力值兑换福袋，优先兑换可负担的最高档位。"""
        if not self._driver.open_heat_exchange_entry():
            return {'error': '未找到热力兑换入口'}

        opened = False
        try:
            if not self._driver.wait_lucky_bag_tab():
                return {'error': '兑换橱窗未打开，未找到兑换福袋标签页'}
            opened = True
            if not self._driver.click_lucky_bag_tab():
                return {'error': '切换到兑换福袋标签页失败'}
            self.logger.info("已切换到兑换福袋标签页")

            current_heat = self._driver.wait_for_heat()
            if current_heat is None:
                return {'error': '兑换橱窗已打开，未读取到热力值'}

            redeemed_count = 0
            capped = True
            for _ in range(MAX_REDEMPTIONS):
                spent = self._driver.redeem_highest_affordable(current_heat)
                if spent is None:
                    capped = False
                    break
                redeemed_count += 1
                next_heat = self._driver.wait_for_heat(below=current_heat)
                if next_heat is None:
                    self.logger.warning(
                        f"Heat points did not decrease after redemption ({current_heat}), aborting loop"
                    )
                    capped = False
                    break
                current_heat = next_heat

            if capped:
                self.logger.warning(f"Reached redemption cap of {MAX_REDEMPTIONS}, stopping")
            self.logger.info(
                f"Redeemed {redeemed_count} luck packs, remaining heat {current_heat}"
            )
            message = f'成功兑换 {redeemed_count} 个福袋，剩余热力值: {current_heat}'
            if capped:
                message += f'（已达单次上限 {MAX_REDEMPTIONS}）'
            return {'message': message}
        except Exception:
            self.logger.error(f"Error redeeming heat: {traceback.format_exc()}")
            return {'error': 'Failed to redeem heat'}
        finally:
            if opened:
                self._driver.exit_exchange_window()
