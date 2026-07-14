import importlib
import sys
import traceback
from datetime import datetime
from pathlib import Path

from ushareiplay.core.command_silence import command_silence
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.command_parser import CommandParser
from ushareiplay.models.message_info import MessageInfo


COMMAND_PREFIXES = (":", "：", "/", "／")
SILENT_COMMAND_PREFIXES = ("/", "／")
PRIVATE_REPLY_PREFIXES = ("$", "＄")
QUEUE_COMMAND_PREFIXES = COMMAND_PREFIXES + PRIVATE_REPLY_PREFIXES
QUEUE_COMMAND_PREFIX_CHARS = "".join(QUEUE_COMMAND_PREFIXES)


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

    def _send_screen_message(self, message: str, silent: bool = False):
        if silent:
            try:
                self.logger.info(f"Silent command suppressed screen message: {message}")
            except Exception:
                pass
            return None
        return self.handler.send_message(message)

    def _send_command_output(self, message_info, response: str, silent: bool = False):
        """Route command execution output to private chat or screen."""
        if not response:
            return None
        if getattr(message_info, "private_reply", False):
            try:
                from ushareiplay.managers.user_manager import UserManager

                sent = UserManager.instance().send_private_message_to_user(
                    message_info.nickname,
                    response,
                )
                if not sent:
                    self.logger.warning(
                        f"Private reply dropped for {message_info.nickname}: send failed"
                    )
                return sent
            except Exception:
                self.logger.error(
                    f"Private reply failed for {message_info.nickname}: {traceback.format_exc()}"
                )
                return False
        return self._send_screen_message(response, silent=silent)

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
            
            # 检查用户等级（系统用户不受限制）
            system_users = self.handler.config.get('system_users', [])
            is_system_user = message_info.nickname in system_users
            
            if not is_system_user:
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

                # Sleep mode: non-system users may be blocked in sleep window
                try:
                    from ushareiplay.managers.sleep_manager import SleepManager

                    prefix = command_info.get("prefix") or ""
                    sleep_exempt = bool(getattr(message_info, "sleep_exempt", False))
                    # Prefer root config (controller.config) so `sleep` can live at top-level.
                    controller = self._get_command_controller()
                    cfg = getattr(controller, "config", None) if controller is not None else None
                    if not isinstance(cfg, dict):
                        cfg = self.handler.config
                    sg = SleepManager.instance(cfg)
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
            
            # UI 互斥：命令执行期间禁止 EventManager 的"未知页面自动 back"打断弹窗/子页面流程
            result = {'error': 'unknown'}
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

            if 'error' in result:
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
        """
        Normalize command-candidate text for robust parsing.

        Accepts:
        - leading whitespace (e.g. "  : help")
        - fullwidth colon (：)
        - silent slash prefixes (/ and ／)
        - whitespace after trigger (e.g. ": help")

        Returns:
            str: cleaned command content WITHOUT the trigger colon, and with
                 leading whitespace removed. Returns "" if no command content.
        """
        if not raw:
            return ""
        s = raw.lstrip()
        if not s:
            return ""
        if s[0] in COMMAND_PREFIXES:
            s = s[1:]
        return s.lstrip()

    def _extract_private_reply_and_normalize(self, raw: str) -> tuple[bool, str]:
        """
        Extract private-reply marker and normalize command candidate.

        Returns:
            tuple[bool, str]: (private_reply, normalized_command_content)
        """
        s = (raw or "").lstrip()
        if not s:
            return False, ""
        private_reply = s.startswith(PRIVATE_REPLY_PREFIXES)
        if private_reply:
            s = s[1:]
        return private_reply, self._normalize_command_candidate(s)

    def _is_silent_command_candidate(self, raw: str) -> bool:
        s = (raw or "").lstrip()
        if s.startswith(PRIVATE_REPLY_PREFIXES):
            s = s[1:].lstrip()
        return bool(s) and s[0] in SILENT_COMMAND_PREFIXES

    async def execute_runtime_queue_messages(self, queue_messages, send_screen_message=None):
        command_messages = []
        for message_info in queue_messages:
            parts = (message_info.content or "").split(";")
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                part = part.replace("{user_name}", message_info.nickname)
                part_silent = bool(getattr(message_info, "silent", False))
                if part.startswith(SILENT_COMMAND_PREFIXES):
                    part_silent = True
                if part.startswith(QUEUE_COMMAND_PREFIXES):
                    command_messages.append(
                        MessageInfo(
                            content=part,
                            nickname=message_info.nickname,
                            silent=part_silent,
                            sleep_exempt=bool(getattr(message_info, "sleep_exempt", False)),
                        )
                    )
                elif not part_silent:
                    if send_screen_message is not None:
                        send_screen_message(part)
                elif self._logger is not None:
                    self._logger.info(f"Silent command suppressed queued message: {part}")

        if not command_messages:
            return 0

        await self.execute_command_messages(command_messages)
        return len(command_messages)

    async def execute_chat_scan(self, chats):
        messages = []
        for chat in chats:
            match = self._match_scanned_chat_command(chat)
            if not match:
                continue

            nickname = match.group(1).strip()
            trigger = match.group(2)
            message_content = match.group(3).strip()
            message_content = f"{trigger}{message_content}" if message_content else ""
            if not message_content.strip(QUEUE_COMMAND_PREFIX_CHARS).strip():
                continue
            messages.append(MessageInfo(message_content, nickname))

        if messages:
            await self.execute_command_messages(messages)

        return messages

    @staticmethod
    def _match_scanned_chat_command(chat: str):
        import re

        pattern = r'souler\[(.+)\]说[:：]\s*([:：/／$＄])\s*(.+)'
        return re.match(pattern, chat)

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
                    self._send_screen_message(
                        f'[{time_prefix}] {cmd} ... @{message_info.nickname}',
                        silent=silent,
                    )

                    command = self.get_command(cmd)
                    if command:
                        response = await self.process_command(command, message_info, command_info)
                        if response:
                            self._send_command_output(message_info, response, silent=silent)
                        success_count += 1
                    else:
                        self.logger.error(f"Unknown command: {cmd}")
                        self._send_screen_message(
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
        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, 'user_return'):
                    await module.command.user_return(username)
            except Exception:
                self.logger.error(f"Error in command user_return: {traceback.format_exc()}")

    async def notify_focus_count_change(self, before: int | None, after: int):
        """
        Notify all commands when 专注人数 (focus_count / tvStudyRoomDesc) changes.

        Args:
            before: Previous parsed count, or None on first observation
            after: New parsed count
        """
        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, "focus_count_change"):
                    await module.command.focus_count_change(before, after)
            except Exception:
                self.logger.error(f"Error in command focus_count_change: {traceback.format_exc()}")
