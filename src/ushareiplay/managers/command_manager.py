import asyncio
import importlib
import sys
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

from ushareiplay.core.chat_intake import (
    QUEUE_COMMAND_PREFIX_CHARS,
    ChatIntakeKind,
    classify_chat_line,
    expand_queue_text,
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

        # Cursor state owned by Command Execution -- the live screen's anchor
        # against which newly visible chat rows are diffed.
        self._recent_chats = deque(maxlen=3)
        self._latest_chats = deque(maxlen=3)

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
        command_messages = []
        for message_info in queue_messages:
            results = expand_queue_text(
                message_info.content,
                message_info.nickname,
                silent=bool(getattr(message_info, "silent", False)),
                sleep_exempt=bool(getattr(message_info, "sleep_exempt", False)),
            )
            for result in results:
                if result.kind == ChatIntakeKind.COMMAND:
                    command_messages.append(
                        MessageInfo(
                            content=result.text,
                            nickname=result.nickname,
                            silent=result.silent,
                            private_reply=result.private_reply,
                            sleep_exempt=result.sleep_exempt,
                        )
                    )
                elif not result.silent:
                    if send_screen_message is not None:
                        send_screen_message(result.text)
                elif self._logger is not None:
                    self._logger.info(f"Silent command suppressed queued message: {result.text}")

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

    # ------------------------------------------------------------------
    # Command Execution seam: visible chat batch -> Chat Intake ->
    # routing -> execution -> outcomes. Owns cursor/dedupe/anchor state,
    # missed-history recovery, and all Chat Intake outcome dispatch.
    # ------------------------------------------------------------------

    @property
    def chat_logger(self):
        # Lazily resolve the chat logger (transport-owned).
        from ushareiplay.managers.message_manager import get_chat_logger

        return get_chat_logger(self.handler.config)

    def _apply_anchor_match(self, content_list):
        # Diff a fresh visible batch against the cursor.
        #
        # Returns ``(latest_chats, missed)``. ``latest_chats`` is the
        # fresh slice that the caller should classify and dispatch.
        # ``missed`` is True when the screen contains rows older than the
        # anchor and we cannot prove the anchor is visible.
        latest_chats = deque(maxlen=3)
        recent_len = len(self._recent_chats)
        content_len = len(content_list)
        missed = False

        if recent_len == 0:
            for content in content_list:
                latest_chats.append(content)
        else:
            for i in range(recent_len):
                no_new = False
                for j in range(content_len):
                    content = content_list[j]
                    ii = i + j
                    if ii < recent_len:
                        recent_chat = self._recent_chats[ii]
                        if content != recent_chat:
                            break
                        if ii == recent_len - 1 and j == content_len - 1:
                            no_new = True
                            break
                    else:
                        latest_chats.append(content)
                if no_new:
                    break
                if len(latest_chats) > 0:
                    break
                elif i == recent_len - 1:
                    missed = True
                    for content in content_list:
                        latest_chats.append(content)

            # Fallback: when the visible window is wider than
            # recent_chats.maxlen (3), every alignment mismatches at j=0
            # because content_list[0] is older than any anchor. If the
            # anchor is still visible, treat that as not-missed and slice
            # the fresh tail off the end.
            if missed and recent_len > 0:
                last_recent = self._recent_chats[-1]
                for idx, content in enumerate(content_list):
                    if content == last_recent:
                        missed = False
                        latest_chats.clear()
                        for new_content in content_list[idx + 1:]:
                            latest_chats.append(new_content)
                        break

        return latest_chats, missed

    async def _dispatch_chat_outcome(self, content):
        # Classify one chat row and route to its outcome sink.
        #
        # Returns ``True`` when the row was a non-empty command (so the
        # caller knows there is at least one command to execute). All
        # rows are logged at the appropriate severity.
        result = classify_chat_line(content)

        if result.kind == ChatIntakeKind.USER_RETURN:
            self.logger.critical(f"User returned: {result.nickname}")
            await self.notify_user_return(result.nickname)
            return False

        if result.kind == ChatIntakeKind.KEYWORD_MENTION:
            from ushareiplay.managers.keyword_manager import KeywordManager

            await KeywordManager.instance().dispatch_mention(
                result, sleep_exempt=True
            )
            self.chat_logger.critical(content)
            return False

        if result.kind == ChatIntakeKind.COMMAND:
            if result.text.strip(QUEUE_COMMAND_PREFIX_CHARS).strip():
                self.chat_logger.critical(content)
                return True
            self.chat_logger.info(content)
            return False

        self.chat_logger.info(content)
        return False

    def _tick_idle_outcome(self):
        # Outcome of a live batch that contained no commands.
        self.update_commands()
        try:
            from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster

            PlaybackBroadcaster.instance().update_playback_info_cache()
        except Exception:
            self.logger.error(
                f"Error updating playback cache: {traceback.format_exc()}"
            )

    async def process_live_batch(self, rows):
        # Process a visible chat batch through the Command Execution seam.
        #
        # Owns dedupe/anchor matching, Chat Intake classification, routing,
        # execution, logging, missed-history recovery, and cursor
        # advancement. Event Processing callers pass the freshly scraped
        # ``rows`` in; this method is the only place that talks to Chat
        # Intake / KeywordManager / PlaybackBroadcaster for live screen
        # updates.
        content_list = [content for content in (rows or []) if content]
        latest_chats, missed = self._apply_anchor_match(content_list)

        has_command = False
        for content in latest_chats:
            if await self._dispatch_chat_outcome(content):
                has_command = True

        if has_command:
            await self.execute_chat_scan(list(latest_chats))
        else:
            self._tick_idle_outcome()

        if missed:
            await self.recover_missed_history()

        # After recovery the view scrolls back to bottom; reset the cursor
        # to the fresh tail so the next iteration does not re-detect a
        # stale gap.
        self._recent_chats.clear()
        for chat in latest_chats:
            self._recent_chats.append(chat)

        return {
            "missed": missed,
            "command_count": sum(
                1
                for chat in latest_chats
                if classify_chat_line(chat).kind == ChatIntakeKind.COMMAND
                and classify_chat_line(chat)
                .text.strip(QUEUE_COMMAND_PREFIX_CHARS)
                .strip()
            ),
        }

    async def recover_missed_history(self):
        # Scroll back to the anchor and queue any missed commands.
        #
        # Mirrors the prior MessageManager.process_missed_messages contract:
        # collapses the seat panel, scrolls the chat list until the anchor
        # (self._recent_chats[-1]) is visible, then enqueues each command
        # that is not already in the anchor/visible-tail sets. Always
        # sends an empty message to scroll back to the bottom after recovery.
        if not self.handler.key_actions.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        try:
            from ushareiplay.managers.message_manager import MessageManager

            seat_manager = MessageManager.instance()._get_seat_manager()
            if seat_manager:
                await seat_manager.prepare_for_chat_scan()
        except Exception:
            self.handler.logger.error(
                f"failed to collapse seat panel (recovery continues): {traceback.format_exc()}"
            )

        last_chat = self._recent_chats[-1] if len(self._recent_chats) > 0 else None
        if not last_chat:
            return None

        self.handler.logger.critical(f"last_chat={last_chat}")

        key, _element, attribute_values = (
            self.handler.gesture_handler.scroll_container_until_element(
                "message_content",
                "message_list",
                "down",
                "content-desc|text",
                last_chat,
            )
        )

        self.handler.send_message("")

        if not key:
            return None

        from ushareiplay.core.message_queue import MessageQueue

        command_set = set[str]()
        nickname_map = {}
        missed_chats = set[str]()

        for chat in attribute_values:
            if last_chat == chat:
                continue
            is_missed = (
                chat not in self._recent_chats
                and chat not in self._latest_chats
                and chat not in missed_chats
            )
            if is_missed:
                self.chat_logger.warning(chat)
                missed_chats.add(chat)

            result = classify_chat_line(chat)

            if result.kind == ChatIntakeKind.KEYWORD_MENTION and is_missed:
                from ushareiplay.managers.keyword_manager import KeywordManager

                await KeywordManager.instance().dispatch_mention(
                    result, sleep_exempt=True
                )
                continue

            if result.kind == ChatIntakeKind.COMMAND:
                command = result.text
                if not command.strip(QUEUE_COMMAND_PREFIX_CHARS).strip():
                    continue
                command_set.add(command)
                nickname_map[command] = result.nickname

        message_queue = MessageQueue.instance()
        for command in command_set:
            message = MessageInfo(command, nickname_map[command])
            await message_queue.put_message(message)
            self.handler.logger.info(f"Missed command added to queue: {command}")

        return command_set

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
