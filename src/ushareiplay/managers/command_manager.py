import asyncio
import importlib
import importlib.util
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ushareiplay.core.chat_intake import (
    QUEUE_COMMAND_PREFIX_CHARS,
    ChatIntakeKind,
    classify_chat_line,
    is_private_reply_prefix,
    is_silent_prefix,
    normalize_command_text,
)
from ushareiplay.core.command_silence import command_silence
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.command_parser import CommandParser
from ushareiplay.models.message_info import MessageInfo


class CommandManager(Singleton):
    """
    命令管理器 - 管理所有命令相关的逻辑
    单例模式，提供统一的命令管理服务
    """

    def __init__(self):
        # 延迟初始化 handler 和 logger，避免循环依赖
        self._handler = None
        self._logger = None
        self._runtime = None
        self.controller = None

        # 命令相关属性
        self.commands_path = Path(__file__).parent.parent / 'commands'
        self.command_modules = {}  # Cache for loaded command modules
        self.command_parser = None  # Will be initialized when needed

    def configure_runtime(self, runtime):
        self._runtime = runtime
        MessageDispatch.instance().configure_runtime(runtime)

    @property
    def runtime(self):
        if self._runtime is None:
            raise RuntimeError("CommandManager runtime has not been configured")
        return self._runtime

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    @property
    def message_dispatch(self):
        return MessageDispatch.instance().bind_handler(self.handler)

    def _get_command_controller(self):
        if self.controller is not None:
            return self.controller
        if self._runtime is not None and hasattr(self._runtime, "controller"):
            return self._runtime.controller
        return None

    def _find_command_class(self, module):
        from ushareiplay.core.base_command import BaseCommand

        candidates = [
            value
            for value in module.__dict__.values()
            if isinstance(value, type)
            and issubclass(value, BaseCommand)
            and value is not BaseCommand
            and value.__module__ == module.__name__
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def initialize_parser(self, commands_config):
        """
        初始化命令解析器
        Args:
            commands_config: 命令配置列表
        """
        self.command_parser = CommandParser(commands_config)
        self.logger.info("Command parser initialized")

    def load_command_module(self, command):
        """Load command module dynamically"""
        try:
            if command in self.command_modules:
                return self.command_modules[command]

            module_path = (self.commands_path / f"{command}.py").resolve()
            if not module_path.exists():
                self.logger.error(f'module path not exists, {module_path}')
                return None

            package_name = f"ushareiplay.commands.{command}"
            spec = importlib.util.spec_from_file_location(package_name, module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)

            if not module:
                self.logger.error('Command module failed to load')
                return None

            if hasattr(module, 'command') and module.command is not None:
                self.command_modules[command] = module
                return module

            controller = self._get_command_controller()
            if controller is None:
                self.logger.error('Command manager does not have a controller reference')
                return None

            command_cls = self._find_command_class(module)
            if command_cls is not None:
                module.command = command_cls(controller)
                self.command_modules[command] = module
                return module

            self.logger.error('Command module does not define a concrete BaseCommand subclass')
            return None

        except Exception:
            self.logger.error(f"Error loading command module {command}: {traceback.format_exc()}")
            return None

    def load_all_commands(self):
        """Load all command modules from commands directory
        Returns:
            dict: Loaded command modules
        """
        try:
            # Get all .py files in commands directory
            command_files = [f.stem for f in self.commands_path.glob('*.py')
                             if f.is_file() and not f.stem.startswith('__')]

            self.logger.info(f"Found command files: {command_files}")

            # Load each command module
            for command in command_files:
                try:
                    module = self.load_command_module(command)
                    if module:
                        self.logger.info(f"Loaded command module: {command}")
                    else:
                        self.logger.error(f"Failed to load command module: {command}")
                except Exception:
                    self.logger.error(f"Error loading command {command}: {traceback.format_exc()}")

        except Exception:
            self.logger.error(f"Error loading commands: {traceback.format_exc()}")

    def update_commands(self):
        """Update all loaded commands"""
        for module in self.command_modules.values():
            try:
                if hasattr(module, 'command'):
                    module.command.update()
            except Exception as e:
                self.logger.error(f"Error updating command {module.__name__}: {str(e)}")

    def get_command(self, command_name):
        """Get command by name"""
        module = self.load_command_module(command_name)
        return module.command if module else None

    @staticmethod
    def _playback_muting():
        from ushareiplay.managers.playback_muting import PlaybackMuting
        return PlaybackMuting.instance()

    @contextmanager
    def playback_muting_guard(self, command, command_info):
        """播放类命令的静音保护上下文。

        未声明 playback_muting 的命令不触碰麦克风；声明了则闭麦执行命令，
        公屏通知发送完毕后等待底层播放就绪再开麦。
        """
        if not getattr(command, "playback_muting", False):
            yield
            return

        parameters = command_info.get("parameters") or []
        with self._playback_muting().guard(
            expected_song=command.playback_expected_song(parameters)
        ):
            yield

    def _report_playback_failure(self, command):
        """播放类命令以错误结果结束时，让静音保护跳过就绪等待并立即开麦。"""
        if not getattr(command, "playback_muting", False):
            return
        self._playback_muting().report_failure()

    async def process_command(self, command, message_info, command_info):
        """Process command using module if available
        Args:
            command: Command instance
            message_info: MessageInfo object
            command_info: dict containing command details
        Returns:
            str: Response message
        """
        try:
            parameters = command_info['parameters']
            silent = bool(command_info.get("silent")) or bool(
                getattr(message_info, "silent", False)
            )

            try:
                self.runtime.emit(
                    "command.received",
                    ctx={
                        "prefix": command_info.get("prefix"),
                        "raw": message_info.content,
                        "nickname": message_info.nickname,
                    },
                )
            except Exception:
                pass
            
            # 角色与权限策略检查
            from ushareiplay.core.roles import RolePolicy
            cfg = getattr(self.handler, "config", None)
            role_policy = RolePolicy(cfg if isinstance(cfg, dict) else None)

            is_human_op = role_policy.is_human_operator(message_info.nickname)

            # 1. 检查用户等级：人工操作者（房主、Console、管理员）与系统自动化角色不受等级限制
            if not role_policy.is_privileged(message_info.nickname):
                required_level = command_info.get('level', 1)
                from ushareiplay.dal.user_dao import UserDAO
                user = await UserDAO.get_or_create(message_info.nickname)
                
                if user.level < required_level:
                    result = {
                        'error': f'需要等级 {required_level} 才能使用此命令，您当前等级为 {user.level}'
                    }
                    format_kwargs = {'user': message_info.nickname, **result}
                    if parameters:
                        format_kwargs['party_id'] = parameters[0]
                    res = command_info['error_template'].format(**format_kwargs)
                    return res

            # 2. 睡眠模式检查 (Sleep mode)：
            # - 人工操作者（房主、Console、管理员）具备人工判断能力，可突破睡眠保护。
            # - 明确标记 sleep_exempt 的指令（如手动 @我 意图识别）可突破睡眠保护。
            # - 系统自动化角色（Timer、Agent）与普通用户不得打断睡眠保护。
            if not is_human_op:
                try:
                    from ushareiplay.managers.sleep_manager import SleepManager

                    prefix = command_info.get("prefix") or ""
                    sleep_exempt = bool(getattr(message_info, "sleep_exempt", False))
                    sg = SleepManager.instance()
                    if not sleep_exempt and sg.is_blocked_command(prefix):
                        result = {
                            "error": (
                                "休息中（11pm-6am）"
                            )
                        }
                        format_kwargs = {"user": message_info.nickname, **result}
                        if parameters:
                            format_kwargs["party_id"] = parameters[0]
                        return command_info["error_template"].format(**format_kwargs)
                except Exception:
                    # Guard should never break command execution.
                    pass

            # 他人房间（客房模式）限制：仅支持点歌功能，所有群管理和配置命令全部禁用
            try:
                from ushareiplay.state.room_state import RoomState
                room_state = RoomState.instance()
                prefix = command_info.get("prefix") or ""
                if room_state.is_guest_room and not room_state.is_command_allowed_in_guest_room(prefix):
                    result = {
                        'error': '当前处于他人房间，仅支持点歌功能，群管理功能已禁用'
                    }
                    format_kwargs = {'user': message_info.nickname, **result}
                    if parameters:
                        format_kwargs['party_id'] = parameters[0]
                    return command_info.get('error_template', '{error}').format(**format_kwargs)
            except Exception:
                pass

            # UI 互斥：命令执行期间禁止 EventManager 的"未知页面自动 back"打断弹窗/子页面流程
            result = {'error': 'unknown'}
            retry_enabled = bool(command_info.get("retry"))
            with command_silence(silent):
                async with self.runtime.ui_session(f"command:{command_info.get('prefix', 'unknown')}"):
                    try:
                        self.runtime.emit(
                            "command.dispatch",
                            ctx={
                                "prefix": command_info.get("prefix"),
                                "parameters": parameters,
                                "nickname": message_info.nickname,
                                "silent": silent,
                            },
                        )
                    except Exception:
                        pass
                    result = await command.process(message_info, parameters)
                    if 'error' in result and retry_enabled:
                        cmd_prefix = command_info.get('prefix', 'unknown')
                        self.logger.warning(
                            f"Command '{cmd_prefix}' failed on first attempt ({result.get('error')}), retrying (1/1)..."
                        )
                        try:
                            self.runtime.emit(
                                "command.retry",
                                ctx={
                                    "prefix": cmd_prefix,
                                    "first_error": result.get("error"),
                                    "nickname": message_info.nickname,
                                },
                            )
                        except Exception:
                            pass
                        await asyncio.sleep(0.5)
                        result = await command.process(message_info, parameters)

            if 'error' in result:
                self._report_playback_failure(command)
                # 合并 result 中的字段（如 party_id），以便各命令的 error_template 能正确渲染
                format_kwargs = {'error': result['error'], 'user': message_info.nickname, **result}
                res = command_info['error_template'].format(**format_kwargs)
            elif 'message' in result:
                # keyword 命令返回的是 message 字段
                res = f'{result["message"]} @{message_info.nickname}'
            else:
                result.setdefault("release_date", "")
                res = f'{command_info["response_template"].format(**result)} @{message_info.nickname}'

            try:
                self.runtime.emit(
                    "command.result",
                    ctx={
                        "prefix": command_info.get("prefix"),
                        "success": "error" not in result,
                        "error": result.get("error") if isinstance(result, dict) else None,
                        "response": res,
                        "response_len": len(res or ""),
                        "silent": silent,
                    },
                )
            except Exception:
                pass
            return res
        except Exception:
            self.logger.error(f"Error processing command {command_info}: {traceback.format_exc()}")
            return f"Error processing command {command_info}"

    def is_valid_command(self, content):
        """Check if content is a valid command"""
        if not self.command_parser:
            self.logger.error("Command parser not initialized")
            return False
        return self.command_parser.is_valid_command(content)

    def parse_command(self, content):
        """Parse command content"""
        if not self.command_parser:
            self.logger.error("Command parser not initialized")
            return None
        return self.command_parser.parse_command(content)

    def _normalize_command_candidate(self, raw: str) -> str:
        """Normalize command-candidate text for robust parsing."""
        return normalize_command_text(raw)

    def _extract_private_reply_and_normalize(self, raw: str) -> tuple[bool, str]:
        """Extract private-reply marker and normalize command candidate."""
        private_reply = is_private_reply_prefix(raw)
        return private_reply, normalize_command_text(raw)

    def _is_silent_command_candidate(self, raw: str) -> bool:
        return is_silent_prefix(raw)

    async def execute_runtime_queue_messages(self, queue_messages, send_screen_message=None):
        from ushareiplay.core.runtime_services import route_queue_text

        command_messages = []
        for message_info in queue_messages:
            routing = route_queue_text(
                message_info.content,
                message_info.nickname,
                source=getattr(message_info, "source", None),
                silent=bool(getattr(message_info, "silent", False)),
                sleep_exempt=bool(getattr(message_info, "sleep_exempt", False)),
            )
            command_messages.extend(routing.commands)

            for screen_text in routing.screen_texts:
                if send_screen_message is not None:
                    send_screen_message(screen_text)

            if self._logger is not None:
                for suppressed in routing.suppressed:
                    self._logger.info(f"Silent command suppressed queued message: {suppressed}")

        if not command_messages:
            return 0

        await self.execute_command_messages(command_messages)
        return len(command_messages)

    async def execute_chat_scan(self, chats):
        messages = []
        for chat in chats:
            result = classify_chat_line(chat)
            if result.kind != ChatIntakeKind.COMMAND:
                continue
            if not result.text.strip(QUEUE_COMMAND_PREFIX_CHARS).strip():
                continue
            messages.append(MessageInfo(result.text, result.nickname))

        if messages:
            await self.execute_command_messages(messages)

        return messages

    async def execute_command_messages(self, messages):
        """
        处理消息中的命令
        Args:
            messages: 消息字典 {msg_id: MessageInfo}
        Returns:
            str: 响应消息（如果有的话）
        """
        success_count = 0

        if not messages:
            return success_count

        # Iterate through message info objects
        for message_info in messages:
            if not message_info.content:
                continue

            # Normalize command input (tolerate leading spaces and spaces after colon)
            extracted_private_reply, content = self._extract_private_reply_and_normalize(
                message_info.content
            )
            message_info.private_reply = bool(
                getattr(message_info, "private_reply", False)
            ) or extracted_private_reply
            silent = bool(getattr(message_info, "silent", False)) or self._is_silent_command_candidate(
                message_info.content
            )
            if not content:
                continue

            if self.is_valid_command(content):
                command_info = self.parse_command(content)
                if command_info:
                    command_info["silent"] = silent
                    # Handle different commands using match-case
                    cmd = command_info['prefix']
                    time_prefix = datetime.now().strftime('%H:%M:%S')
                    self.message_dispatch.send_screen_message(
                        f'[{time_prefix}] {cmd} ... @{message_info.nickname}',
                        silent=silent,
                    )

                    command = self.get_command(cmd)
                    if command:
                        # 播放静音保护：闭麦 -> 点歌/切歌 -> 公屏通知 -> 等待播放就绪 -> 开麦
                        with self.playback_muting_guard(command, command_info):
                            response = await self.process_command(command, message_info, command_info)
                            if response:
                                self.message_dispatch.send_for_message_info(
                                    message_info, response, silent=silent
                                )
                        success_count += 1
                    else:
                        self.logger.error(f"Unknown command: {cmd}")
                        self.message_dispatch.send_screen_message(
                            f'[{time_prefix}] Unknown command: {cmd} @{message_info.nickname}',
                            silent=silent,
                        )

        self.logger.info(f"{success_count}/{len(messages)} commands processed")

        return success_count

    async def handle_message_commands(self, messages):
        return await self.execute_command_messages(messages)

    def get_command_modules(self):
        """获取所有已加载的命令模块"""
        return self.command_modules

    async def notify_user_leave(self, username: str):
        """
        Notify all commands when a user leaves.
        For avatar users (with canonical mapping), only triggers when ALL aliases
        of the same canonical user are offline.

        Args:
            username: Username of the user who left
        """
        try:
            from ushareiplay.dal.user_dao import UserDAO
            from ushareiplay.managers.info_manager import InfoManager

            all_avatars = await UserDAO.get_all_avatar_usernames(username)
            online_users = InfoManager.instance().get_online_users()
            still_online = all_avatars & online_users

            if still_online:
                self.logger.info(
                    f"User leave skipped for '{username}': "
                    f"avatars still online: {still_online}"
                )
                return

            # 以主账号 canonical username 触发退出事件
            raw_user = await UserDAO.get_or_create_raw(username)
            canonical_user = await UserDAO.resolve_canonical(raw_user)
            canonical_username = canonical_user.username

            self.logger.info(
                f"All avatars offline for '{username}' → triggering user_leave "
                f"as canonical '{canonical_username}'"
            )

            # Schedule memory consolidation for the leaving user (canonical)
            try:
                from ushareiplay.managers.memory_manager import MemoryManager
                if MemoryManager.is_initialized():
                    MemoryManager.instance().schedule_consolidation_user(canonical_username)
            except Exception:
                self.logger.warning(f"Failed to schedule memory consolidation for user_leave '{canonical_username}'")

            for module in self.get_command_modules().values():
                try:
                    if hasattr(module.command, 'user_leave'):
                        await module.command.user_leave(canonical_username)
                except Exception:
                    self.logger.error(f"Error in command user_leave: {traceback.format_exc()}")

        except Exception:
            self.logger.error(f"Error in notify_user_leave: {traceback.format_exc()}")

    async def notify_user_enter(self, username: str):
        """
        Notify all commands when a user enters

        Args:
            username: Username of the user who entered
        """
        try:
            from ushareiplay.managers.memory_manager import MemoryManager
            if MemoryManager.is_initialized():
                MemoryManager.instance().schedule_consolidation_user(username)
        except Exception:
            self.logger.warning(f"Failed to schedule memory consolidation for user_enter '{username}'")

        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, 'user_enter'):
                    await module.command.user_enter(username)
            except Exception:
                self.logger.error(f"Error in command user_enter: {traceback.format_exc()}")

    async def notify_user_return(self, username: str):
        """
        Notify all commands when a user returns（用户重新打开 app 返回派对）

        Args:
            username: Username of the user who returned
        """
        try:
            from ushareiplay.managers.memory_manager import MemoryManager
            if MemoryManager.is_initialized():
                MemoryManager.instance().schedule_consolidation_user(username)
        except Exception:
            self.logger.warning(f"Failed to schedule memory consolidation for user_return '{username}'")

        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, 'user_return'):
                    await module.command.user_return(username)
            except Exception:
                self.logger.error(f"Error in command user_return: {traceback.format_exc()}")


    async def notify_gift_receive(self, username: str):
        """
        Notify all commands when a gift or heat contribution is received

        Args:
            username: Username of the user who sent the gift
        """
        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, 'user_gift_receive'):
                    await module.command.user_gift_receive(username)
            except Exception:
                self.logger.error(f"Error in command user_gift_receive: {traceback.format_exc()}")

    async def notify_focus_count_change(
        self,
        before: int | None,
        after: int,
        changed_users: list[str] | None = None,
        seat_info: dict | None = None,
    ):
        """
        Notify all commands when 专注人数 (focus_count / tvStudyRoomDesc) or seats change.

        Args:
            before: Previous parsed count, or None on first observation
            after: New parsed count
            changed_users: Specific users whose seat/focus status changed, or None for all
            seat_info: Optional dictionary mapping username to seat details
        """
        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, "focus_count_change"):
                    await module.command.focus_count_change(
                        before, after, changed_users=changed_users, seat_info=seat_info
                    )
            except Exception:
                self.logger.error(f"Error in command focus_count_change: {traceback.format_exc()}")
