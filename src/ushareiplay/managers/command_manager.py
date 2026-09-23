import asyncio
import importlib
import importlib.util
import sys
import traceback
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ushareiplay.core.chat_intake import (
    QUEUE_COMMAND_PREFIX_CHARS,
    ChatIntakeKind,
    classify_chat_line,
    expand_queue_text,
    format_manual_message,
    is_manual_operator,
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

    @property
    def recent_chats(self):
        return self._recent_chats

    @recent_chats.setter
    def recent_chats(self, val):
        self._recent_chats = val

    @property
    def latest_chats(self):
        return self._latest_chats

    @latest_chats.setter
    def latest_chats(self, val):
        self._latest_chats = val

    def get_room_owner(self) -> str | None:
        if hasattr(self.handler, 'config') and isinstance(self.handler.config, dict):
            soul_cfg = self.handler.config.get("soul", {})
            if isinstance(soul_cfg, dict):
                owner = soul_cfg.get("room_owner") or soul_cfg.get("owner_username")
                if owner:
                    return owner
            return self.handler.config.get("room_owner") or self.handler.config.get("owner_username")
        return None

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
                    screen_text = (
                        format_manual_message(result.text)
                        if is_manual_operator(result.nickname, getattr(message_info, "source", None))
                        else result.text
                    )
                    if send_screen_message is not None:
                        send_screen_message(screen_text)
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
        room_owner = self.get_room_owner()
        result = classify_chat_line(content, room_owner=room_owner)

        if result.kind == ChatIntakeKind.USER_RETURN:
            from ushareiplay.state.presence_tracker import PresenceTracker
            presence_tracker = PresenceTracker.instance()
            if presence_tracker.should_trigger_return(result.nickname):
                presence_tracker.record_return(result.nickname)
                self.logger.critical(f"User returned: {result.nickname}")
                self.chat_logger.critical(content)
                await self.notify_user_return(result.nickname)
            else:
                self.logger.info(
                    f"User entrance message for '{result.nickname}' skipped return event (not online or recently entered/returned)"
                )
                self.chat_logger.info(content)
            return False

        if result.kind == ChatIntakeKind.GIFT_RECEIVE:
            self.chat_logger.critical(content)
            if getattr(result, "heat_value", 0) > 0:
                self.logger.info(
                    f"Heat contribution received from user '{result.nickname}': +{result.heat_value} heat"
                )
            else:
                self.logger.info(
                    f"Gift received from user '{result.nickname}' (sent to room_owner '{room_owner}')"
                )
            await self._handle_gift_receive(result)
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

    async def _handle_gift_receive(self, result):
        """处理收礼物与热力值贡献：自动升级等级、发送感谢消息、触发自定义命令"""
        try:
            from ushareiplay.dal.user_dao import UserDAO
            from ushareiplay.core.message_queue import MessageQueue
            from ushareiplay.models.message_info import MessageInfo

            username = result.nickname
            heat_val = getattr(result, "heat_value", 0)
            if heat_val > 0:
                user = await UserDAO.record_heat_contribution(username, heat_val)
            else:
                user = await UserDAO.record_owner_gift(username)

            if user:
                self.logger.info(
                    f"User '{user.username}' status after gift/heat processing: level=L{user.level}, cumulative_heat={user.heat_value}"
                )

            # 自动发送 @用户 谢谢
            thank_msg = MessageInfo(
                content=f"@{username} 谢谢",
                nickname=username,
            )
            await MessageQueue.instance().put_message(thank_msg)
            self.logger.info(f"Enqueued thank-you message '@{username} 谢谢' to MessageQueue")

            # 触发命令管理器的收礼物通知
            await self.notify_gift_receive(username)
        except Exception:
            self.logger.error(f"Error handling gift receive: {traceback.format_exc()}")

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

        from ushareiplay.core.chat_intake import strip_quoted_segment
        anchor = strip_quoted_segment(last_chat) or last_chat

        self.handler.logger.critical(f"last_chat={last_chat}")

        key, _element, attribute_values = (
            self.handler.gesture_handler.scroll_container_until_element(
                "message_content",
                "message_list",
                "down",
                "content-desc|text",
                anchor,
            )
        )

        self.handler.send_message("")

        if not key:
            return None

        from ushareiplay.core.message_queue import MessageQueue

        command_set = set[str]()
        nickname_map = {}
        missed_chats = set[str]()
        known_chats = {strip_quoted_segment(chat) for chat in self._recent_chats}
        known_chats.update(strip_quoted_segment(chat) for chat in self._latest_chats)
        room_owner = self.get_room_owner()

        for chat in attribute_values:
            if anchor == strip_quoted_segment(chat):
                continue
            is_missed = (
                chat not in known_chats
                and chat not in missed_chats
            )
            if is_missed:
                self.chat_logger.warning(chat)
                missed_chats.add(chat)

            result = classify_chat_line(chat, room_owner=room_owner)

            if result.kind == ChatIntakeKind.KEYWORD_MENTION and is_missed:
                from ushareiplay.managers.keyword_manager import KeywordManager

                await KeywordManager.instance().dispatch_mention(
                    result, sleep_exempt=True
                )
                continue

            if result.kind == ChatIntakeKind.GIFT_RECEIVE and is_missed:
                from ushareiplay.dal.user_dao import UserDAO

                username = result.nickname
                heat_val = getattr(result, "heat_value", 0)
                if heat_val > 0:
                    user = await UserDAO.record_heat_contribution(username, heat_val)
                    if user:
                        self.handler.logger.info(
                            f"Missed heat contribution processed for user '{user.username}': level=L{user.level}, cumulative_heat={user.heat_value}"
                        )
                else:
                    user = await UserDAO.record_owner_gift(username)
                    if user:
                        self.handler.logger.info(
                            f"Missed gift processed for user '{user.username}': level=L{user.level}"
                        )

                thank_msg = MessageInfo(
                    content=f"@{username} 谢谢",
                    nickname=username,
                )
                await MessageQueue.instance().put_message(thank_msg)
                self.handler.logger.info(f"Enqueued thank-you message '@{username} 谢谢' to MessageQueue")
                await self.notify_gift_receive(username)
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
