"""命令用例：睡眠窗口策略与派发门禁。

`DispatchCommand` 拥有命令执行前的全部门禁（等级、睡眠、客房）、重试、
静音上下文与运行时事件；门禁失败抛领域异常，由入站适配器翻译成既有文案。
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, ContextManager, Optional

from ushareiplay.modules.command.domain import (
    DEFAULT_SLEEP_ENABLED,
    DEFAULT_SLEEP_WINDOW_END,
    DEFAULT_SLEEP_WINDOW_START,
    CommandCatalogue,
    GuestRoomRestricted,
    InsufficientCommandLevel,
    NaturalLanguageContext,
    NaturalLanguageResult,
    SleepBlocked,
    SleepWindow,
    UnknownCommand,
    parse_enabled,
    parse_hhmm,
)
from ushareiplay.modules.command.ports import (
    CommandRuntime,
    GuestRoomPolicy,
    NaturalLanguageResolver,
    SleepPolicy,
)
from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.shared.ports import Clock
from ushareiplay.modules.shared.roles import (
    RolePolicy,
    min_command_level,
    resolve_command_level,
)
from ushareiplay.modules.user.ports import UserRepository


class SleepManager:
    """
    SleepManager (睡眠模式)

    - Reads config from a merged dict (config.yaml + config.local.yaml result).
    - Provides a guard window check and command blocking decision.

    普通对象：由组合根构造后注入 `CommandManager` / 配置热重载器。
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


class ResolveNaturalLanguage:
    """把 @我 触发的自然语言翻译成标准命令或聊天回复（ADR-0003）。

    提示词构建与开关判定留在用例里；LLM 传输由注入的 `NaturalLanguageResolver`
    端口负责。解析失败/超时返回 None，调用方回落到普通聊天回复（default keyword）。
    """

    def __init__(
        self, resolver: NaturalLanguageResolver, config: dict | None = None
    ):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.api_key = str(cfg.get("api_key", "")).strip()
        self.model = str(cfg.get("model", "deepseek-chat"))
        self.timeout = float(cfg.get("timeout", 4.0))
        self._custom_prompt = str(
            cfg.get("custom_prompt") or cfg.get("system_prompt") or ""
        ).strip()
        system_users_cfg = cfg.get("system_users")
        if system_users_cfg is not None:
            self._system_users = set(system_users_cfg)
        else:
            self._system_users = {"Timer", "Console", "Agent"}
        self._resolver = resolver
        self._logger = logging.getLogger("ResolveNaturalLanguage")

    def _format_player_description(self, player: str, system_users: set[str]) -> str:
        """Format player name, distinguishing system users."""
        if not player:
            return ""
        if player in system_users or player.lower() in {u.lower() for u in system_users}:
            p_lower = player.lower()
            if p_lower == "timer":
                return f"{player} (系统定时器自动播放)"
            elif p_lower == "console":
                return f"{player} (系统控制台/后台指令)"
            elif p_lower == "agent":
                return f"{player} (系统智能体/后台任务)"
            return f"{player} (系统自动化任务/非普通用户)"
        return player

    def _build_system_prompt(
        self,
        user_name: str,
        user_level: int,
        commands_config: list[dict],
        playback_info: Optional[dict] = None,
        room_info: Optional[dict] = None,
        memory_context: Optional[dict] = None,
        command_catalogue: Optional[object] = None,
    ) -> str:
        """Construct the system prompt with command schemas, user context, playback state, room state, and memory."""
        if command_catalogue is not None:
            cmd_lines = command_catalogue.get_prompt_lines(
                guest_room=bool(room_info and room_info.get("is_guest_room"))
            )
        else:
            cmd_lines = []
            for cmd in commands_config or []:
                prefix = cmd.get("prefix", "")
                if not prefix:
                    continue
                lvl = min_command_level(cmd)
                desc = cmd.get("description") or cmd.get("response_template") or prefix
                cmd_lines.append(f"- `:{prefix}` (所需等级: L{lvl}): {desc}")

        cmd_table = "\n".join(cmd_lines) if cmd_lines else "- `:play` (所需等级: L1): 播放指定歌曲"

        playback_lines = []
        playback_desc = "无"
        if playback_info:
            song = playback_info.get("song") or ""
            singer = playback_info.get("singer") or ""
            if song and song != "Unknown":
                playback_desc = f"{song} - {singer}" if (singer and singer != "Unknown") else song
        playback_lines.append(f"- 当前正在播放歌曲: {playback_desc}")

        if playback_info:
            player = playback_info.get("player")
            if player:
                player_desc = self._format_player_description(player, self._system_users)
                playback_lines.append(f"- 当前播放者/点歌人: {player_desc}")

            playlist_name = playback_info.get("playlist_name")
            if playlist_name:
                ptype = playback_info.get("playlist_type") or "歌单"
                if player:
                    is_sys = player in self._system_users or player.lower() in {u.lower() for u in self._system_users}
                    owner_tag = f" (by {player} [系统播放])" if is_sys else f" (by {player})"
                else:
                    owner_tag = ""
                playback_lines.append(f"- 当前播放列表/歌单: [{ptype}] {playlist_name}{owner_tag}")
            else:
                playback_lines.append("- 当前播放列表/歌单: 暂无活跃歌单")

            play_mode = playback_info.get("play_mode")
            if play_mode and play_mode != "未知":
                playback_lines.append(f"- 播放模式: {play_mode}")
        else:
            playback_lines.append("- 当前播放列表/歌单: 暂无活跃歌单")

        playback_section = "\n".join(playback_lines)

        room_desc_lines = []
        if room_info:
            is_guest = room_info.get("is_guest_room", False)
            room_type_str = "他人房间（客房模式，仅支持点歌）" if is_guest else "主房间（宿主模式，支持全部功能）"
            room_desc_lines.append(f"- 房间类型: {room_type_str}")
            room_id = room_info.get("room_id")
            if room_id:
                room_desc_lines.append(f"- 房间ID: {room_id}")
            user_count = room_info.get("user_count")
            if user_count is not None:
                room_desc_lines.append(f"- 在线人数: {user_count}人")
            focus_count = room_info.get("focus_count")
            if focus_count is not None:
                room_desc_lines.append(f"- 专注人数: {focus_count}人")
            rec = room_info.get("recommendation_enabled")
            if rec is not None:
                room_desc_lines.append(f"- 派对推荐: {'开启' if rec else '关闭'}")
        else:
            room_desc_lines.append("- 房间类型: 主房间（宿主模式）")

        room_desc = "\n".join(room_desc_lines)

        memory_section = ""
        if memory_context:
            mem_lines = []
            directives = memory_context.get("directives") or []
            profile = (memory_context.get("profile") or "").strip()
            short_term = memory_context.get("short_term_chats") or []

            if directives or profile:
                mem_lines.append("【用户长期记忆与核心设定 (铁律区 - 必须严格遵守)】")
                if directives:
                    mem_lines.append("- 核心称谓与铁律指令 (不可违背):")
                    for d in directives:
                        mem_lines.append(f"  * {d}")
                if profile:
                    mem_lines.append(f"- 用户画像与偏好特点:\n  {profile}")

            if short_term:
                mem_lines.append("【近期临时对话记录（短期记忆）】")
                for msg in short_term:
                    mem_lines.append(f"- 用户发言: {msg}")

            if mem_lines:
                memory_section = "\n\n" + "\n".join(mem_lines)

        custom_section = ""
        if self._custom_prompt:
            custom_section = f"\n\n【用户自定义行为指令 / 补充设定】\n{self._custom_prompt}"

        return f"""你是一个智能派对房间命令解析助手。你的任务是将用户的自然语言转换为标准命令或友好的中文回复。

【当前环境与上下文】
- 发言用户: {user_name}
- 用户权限等级: L{user_level}
{playback_section}
{room_desc}{memory_section}

【可用系统命令列表】
{cmd_table}

【输出规则】
1. 必须且只能输出严格的 JSON 格式，不要包含任何 markdown 代码块标记以外的多余解释。
2. JSON 格式: {{"type": "command" | "reply", "content": "..."}}
3. 如果用户意图为执行某个命令:
   - 若 用户等级 >= 命令所需等级: 输出 {{"type": "command", "content": ":<命令前缀> <参数>"}}，如 {{"type": "command", "content": ":play 周杰伦 晴天"}} 或 {{"type": "command", "content": ":next"}}。
   - 若 用户等级 < 命令所需等级: 输出 {{"type": "reply", "content": "你的权限不足（当前等级 L{user_level}，需要 L<所需等级>），请关注群主或联系房管升级~"}}。
4. 如果用户表达的是代词（如“这首歌”、“重新播放”、“再放一遍”），结合当前正在播放歌曲转译出准确的歌曲命令。
5. 如果用户询问当前房间状态（如房间ID、当前是在主房间还是他人房间、在线人数、推荐状态等），结合【当前环境与上下文】中的房间信息用友好的中文直接回答。
6. 如果用户询问当前播放状态（如“现在是播我的歌单吗”、“现在在播谁的歌/歌单”、“当前播的是什么歌单”、“当前播放模式是什么”等）:
   - 必须对比发言用户与【当前环境与上下文】中的当前播放者/点歌人及歌单信息。
   - 若当前播放者是系统用户（如 Timer、Console、Agent 等系统角色）：必须明确告知当前是由系统（如定时任务、控制台或系统自动化）自动播放，而非普通房间听众点播；若用户询问是否是自己的歌单，明确告知是系统自动播放。
   - 若发言用户与当前播放者一致且有活跃歌单（且非系统用户），明确肯定回复（例如“是的，当前正在播放你的歌单《...》哦~”）。
   - 若发言用户与当前播放者不一致（且播放者为其他普通用户），明确告知当前正在播放的是哪位用户点播的歌/歌单。
   - 若当前暂无活跃歌单或未在播放歌曲，也如实友好回答。
7. 如果用户只是日常打招呼、闲聊、调侃或提问（非命令）:
   - 输出 {{"type": "reply", "content": "<简短友好的中文回复>"}}。
8. 如果用户意图完全无法理解或无法匹配任何操作:
   - 输出 {{"type": "reply", "content": "未能理解你的指令，你可以直接发送 :play 歌名 点歌哦~"}}。
9. 若存在【用户长期记忆与核心设定】，回复中必须严格遵守铁律区中的用户称谓与偏好设定；结合近期临时对话记录保持多轮对话连贯自然。{custom_section}
"""

    async def resolve(
        self,
        user_text: str,
        user_name: str,
        user_level: int = 0,
        commands_config: Optional[list[dict]] = None,
        playback_info: Optional[dict] = None,
        room_info: Optional[dict] = None,
        memory_context: Optional[dict] = None,
        command_catalogue: Optional[object] = None,
    ) -> Optional[NaturalLanguageResult]:
        """Resolve a natural language user utterance into a command or reply.

        Returns the resolver result, or None when disabled/error/timeout so the
        caller falls back to the normal chat reply.
        """
        if not self.enabled or not self.api_key or not user_text:
            return None

        context = NaturalLanguageContext(
            system_prompt=self._build_system_prompt(
                user_name=user_name,
                user_level=user_level,
                commands_config=commands_config or [],
                playback_info=playback_info,
                room_info=room_info,
                memory_context=memory_context,
                command_catalogue=command_catalogue,
            ),
            model=self.model,
            timeout=self.timeout,
        )
        try:
            return await self._resolver.resolve(user_text, context)
        except Exception as e:
            self._logger.warning(
                f"NaturalLanguageResolver error during resolution: {e}"
            )
            return None
