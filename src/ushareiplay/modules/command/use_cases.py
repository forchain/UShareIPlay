"""命令用例：睡眠窗口策略与派发门禁。

`DispatchCommand` 拥有命令执行前的全部门禁（等级、睡眠、客房）、重试、
静音上下文与运行时事件；门禁失败抛领域异常，由入站适配器翻译成既有文案。
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, ContextManager, Optional

from ushareiplay.core.singleton import Singleton
from ushareiplay.modules.command.domain import (
    DEFAULT_SLEEP_ENABLED,
    DEFAULT_SLEEP_WINDOW_END,
    DEFAULT_SLEEP_WINDOW_START,
    CommandCatalogue,
    GuestRoomRestricted,
    InsufficientCommandLevel,
    SleepBlocked,
    SleepWindow,
    UnknownCommand,
    parse_enabled,
    parse_hhmm,
)
from ushareiplay.modules.command.ports import (
    CommandRuntime,
    GuestRoomPolicy,
    SleepPolicy,
)
from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.shared.ports import Clock
from ushareiplay.modules.shared.roles import RolePolicy, resolve_command_level
from ushareiplay.modules.user.ports import UserRepository


class SleepManager(Singleton):
    """
    SleepManager (睡眠模式)

    - Reads config from a merged dict (config.yaml + config.local.yaml result).
    - Provides a guard window check and command blocking decision.
    """

    DEFAULT_ENABLED = DEFAULT_SLEEP_ENABLED
    DEFAULT_WINDOW_START = DEFAULT_SLEEP_WINDOW_START
    DEFAULT_WINDOW_END = DEFAULT_SLEEP_WINDOW_END

    def __init__(self, config: dict | None = None, catalogue: CommandCatalogue | None = None):
        if isinstance(config, ConfigView):
            self._config = config
            sleep_section = config.maybe_section("sleep")
            sleep_cfg = dict(sleep_section.data) if sleep_section else {}
        else:
            self._config = config or {}
            sleep_cfg = self._config.get("sleep")
            if not isinstance(sleep_cfg, dict):
                sleep_cfg = {}
        self._catalogue = catalogue or CommandCatalogue.from_config(self._config)

        self._enabled = parse_enabled(sleep_cfg.get("enabled"), self.DEFAULT_ENABLED)
        self._override_enabled: bool | None = None

        # Spec prefers sleep.start/end. Keep sleep.window.start/end as a compatible fallback.
        window = sleep_cfg.get("window") or {}
        if not isinstance(window, dict):
            window = {}

        start_raw = sleep_cfg.get("start")
        if start_raw is None:
            start_raw = window.get("start")
        if start_raw is None:
            start_raw = self.DEFAULT_WINDOW_START.strftime("%H:%M")

        end_raw = sleep_cfg.get("end")
        if end_raw is None:
            end_raw = window.get("end")
        if end_raw is None:
            end_raw = self.DEFAULT_WINDOW_END.strftime("%H:%M")

        self._window_start_str = (
            start_raw if isinstance(start_raw, str) else self.DEFAULT_WINDOW_START.strftime("%H:%M")
        )
        self._window_end_str = end_raw if isinstance(end_raw, str) else self.DEFAULT_WINDOW_END.strftime("%H:%M")

        start = parse_hhmm(start_raw)
        end = parse_hhmm(end_raw)
        self._window: SleepWindow | None = SleepWindow(start, end) if start and end else None

    def configure_catalogue(self, catalogue: CommandCatalogue) -> None:
        """配置热重载后换用新的命令目录（目录本身不可变）。"""
        self._catalogue = catalogue

    def set_override(self, enabled: bool | None) -> None:
        if enabled is None:
            self._override_enabled = None
        else:
            self._override_enabled = bool(enabled)

    def get_default_enabled(self) -> bool:
        return self._enabled

    def get_override(self) -> bool | None:
        return self._override_enabled

    @property
    def effective_enabled(self) -> bool:
        if self._override_enabled is not None:
            return self._override_enabled
        return self._enabled

    def _resolve_time(self, now: dt.time | dt.datetime | None) -> dt.time | None:
        if now is None:
            return dt.datetime.now().time()
        if isinstance(now, dt.datetime):
            return now.time()
        if isinstance(now, dt.time):
            return now
        return None

    def is_in_configured_window(self, now: dt.time | dt.datetime | None = None) -> bool:
        """
        Check whether `now` is inside the configured sleep window only.

        This method MUST NOT be affected by enabled/override; it answers purely
        "is the time within the configured window?"
        """
        if self._window is None:
            # Parse failure: safe default is "do not block"
            return False

        t = self._resolve_time(now)
        if t is None:
            return False

        return self._window.contains(t)

    def is_in_sleep_window(self, now: dt.time | dt.datetime | None = None) -> bool:
        if not self.effective_enabled:
            return False
        return self.is_in_configured_window(now)

    # Backwards-compatible alias: older code/tests used "guard window".
    def is_in_guard_window(self, now: dt.time | dt.datetime | None = None) -> bool:
        return self.is_in_sleep_window(now)

    def get_window_start_str(self) -> str:
        return self._window_start_str

    def get_window_end_str(self) -> str:
        return self._window_end_str

    def get_window_display(self) -> str:
        return f"{self._window_start_str}-{self._window_end_str}"

    def is_blocked_command(self, command: str, now: dt.time | dt.datetime | None = None) -> bool:
        if not isinstance(command, str):
            return False
        cmd = command.strip().lower()
        if not cmd:
            return False
        if not self._catalogue.is_sleep_blocked(cmd):
            return False
        return self.is_in_sleep_window(now)


class DispatchCommand:
    """执行一条命令：门禁 → 静音/UI 会话 → 重试 → 结果渲染。"""

    def __init__(
        self,
        *,
        policy: RolePolicy,
        catalogue: Optional[CommandCatalogue],
        users: UserRepository,
        runtime: CommandRuntime,
        clock: Clock,
        silence: Callable[[bool], ContextManager],
        sleep: Optional[SleepPolicy] = None,
        room: Optional[GuestRoomPolicy] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._policy = policy
        self._catalogue = catalogue
        self._users = users
        self._runtime = runtime
        self._clock = clock
        self._silence = silence
        self._sleep = sleep
        self._room = room
        self._logger = logger or logging.getLogger("DispatchCommand")

    async def execute(self, command, message_info, command_info) -> str:
        if command is None:
            raise UnknownCommand(command_info.get("prefix") or "")

        parameters = command_info["parameters"]
        silent = bool(command_info.get("silent")) or bool(
            getattr(message_info, "silent", False)
        )

        self._emit(
            "command.received",
            {
                "prefix": command_info.get("prefix"),
                "raw": message_info.content,
                "nickname": message_info.nickname,
            },
        )

        await self._check_level(message_info, command_info, parameters)
        self._check_sleep(message_info, command_info)
        self._check_guest_room(command_info)

        # UI 互斥：命令执行期间禁止 EventManager 的"未知页面自动 back"打断弹窗/子页面流程
        retry_enabled = bool(command_info.get("retry"))
        with self._silence(silent):
            async with self._runtime.ui_session(
                f"command:{command_info.get('prefix', 'unknown')}"
            ):
                self._emit(
                    "command.dispatch",
                    {
                        "prefix": command_info.get("prefix"),
                        "parameters": parameters,
                        "nickname": message_info.nickname,
                        "silent": silent,
                    },
                )
                result = await command.process(message_info, parameters)
                if "error" in result and retry_enabled:
                    cmd_prefix = command_info.get("prefix", "unknown")
                    self._logger.warning(
                        f"Command '{cmd_prefix}' failed on first attempt ({result.get('error')}), retrying (1/1)..."
                    )
                    self._emit(
                        "command.retry",
                        {
                            "prefix": cmd_prefix,
                            "first_error": result.get("error"),
                            "nickname": message_info.nickname,
                        },
                    )
                    await self._clock.sleep(0.5)
                    result = await command.process(message_info, parameters)

        if "error" in result:
            # 合并 result 中的字段（如 party_id），以便各命令的 error_template 能正确渲染
            format_kwargs = {
                "error": result["error"],
                "user": message_info.nickname,
                **result,
            }
            res = command_info["error_template"].format(**format_kwargs)
        elif "message" in result:
            # keyword 命令返回的是 message 字段
            res = f'{result["message"]} @{message_info.nickname}'
        else:
            result.setdefault("release_date", "")
            res = (
                f'{command_info["response_template"].format(**result)} '
                f"@{message_info.nickname}"
            )

        self._emit(
            "command.result",
            {
                "prefix": command_info.get("prefix"),
                "success": "error" not in result,
                "error": result.get("error") if isinstance(result, dict) else None,
                "response": res,
                "response_len": len(res or ""),
                "silent": silent,
            },
        )
        return res

    async def _check_level(self, message_info, command_info, parameters):
        if self._policy.is_privileged(message_info.nickname):
            return
        prefix = command_info.get("prefix") or ""
        required_level = (
            self._catalogue.required_level(prefix, parameters)
            if self._catalogue is not None and self._catalogue.get(prefix)
            else resolve_command_level(command_info, parameters)
        )
        user = await self._users.get_or_create(message_info.nickname)
        if user.level < required_level:
            raise InsufficientCommandLevel(required_level, user.level)

    def _check_sleep(self, message_info, command_info) -> None:
        # 人工操作者（房主、管理员）具备人工判断能力，可突破睡眠保护。
        if self._policy.is_human_operator(message_info.nickname):
            return
        if getattr(message_info, "sleep_exempt", False):
            return
        prefix = command_info.get("prefix") or ""
        try:
            blocked = self._sleep is not None and self._sleep.is_blocked_command(prefix)
        except Exception:
            # Guard should never break command execution.
            blocked = False
        if blocked:
            raise SleepBlocked()

    def _check_guest_room(self, command_info) -> None:
        # 他人房间（客房模式）限制：仅支持点歌功能，所有群管理和配置命令全部禁用
        try:
            if self._room is None or not self._room.is_guest_room:
                return
            prefix = command_info.get("prefix") or ""
            allowed = self._room.is_command_allowed_in_guest_room(prefix)
        except Exception:
            return
        if not allowed:
            raise GuestRoomRestricted()

    def _emit(self, event: str, ctx: dict) -> None:
        try:
            self._runtime.emit(event, ctx=ctx)
        except Exception:
            pass
