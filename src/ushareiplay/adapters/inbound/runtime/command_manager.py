import importlib
import importlib.util
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.adapters.outbound.system.clock import SystemClock
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.core.chat_intake import MessageBatch, normalize_command_text
from ushareiplay.core.command_silence import command_silence
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.core.runtime_services import route_queue_text
from ushareiplay.core.singleton import Singleton
from ushareiplay.modules.command.domain import (
    CHAT_COMMANDS_PATH,
    DEFAULT_COMMANDS_PATH,
    CommandCatalogue,
    GuestRoomRestricted,
    InsufficientCommandLevel,
    SleepBlocked,
)
from ushareiplay.modules.command.use_cases import DispatchCommand
from ushareiplay.modules.shared.roles import RolePolicy
from ushareiplay.modules.room.macros import SEAT_INFO_CTX_KEY
from ushareiplay.modules.room.registry import ENTER, EXIT, FOCUS, RECEIVE, RETURN
from ushareiplay.models.message_info import MessageInfo


class CommandManager(Singleton):
    """
    命令管理器 - 管理所有命令相关的逻辑
    单例模式，提供统一的命令管理服务
    """

    def __init__(self, handler=None, sleep=None, room_state=None, user_event_hooks=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)
        self._runtime = None
        self.controller = None
        self.user_memory = None
        self._sleep = sleep
        self.room_state = room_state
        self.user_event_hooks = user_event_hooks

        # 命令相关属性：启动校验与动态加载共用同一份有序根列表。
        self.commands_path = DEFAULT_COMMANDS_PATH
        self.command_roots = (CHAT_COMMANDS_PATH, self.commands_path)
        self.command_modules = {}  # Cache for loaded command modules
        self.catalogue = None  # Built from config by initialize_parser()
        self._users = TortoiseUserRepository()
        self._clock = SystemClock()

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
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._handler, "logger", None) or logging.getLogger("CommandManager")
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

    def initialize_parser(self, config):
        """
        初始化命令目录
        Args:
            config: 根配置（含 commands / sleep），或直接传入命令列表
        """
        self.catalogue = (
            config
            if isinstance(config, CommandCatalogue)
            else CommandCatalogue.from_config(config)
        )
        self.logger.info("Command parser initialized")

    @staticmethod
    def _module_name(module_path: Path, command: str) -> str:
        """按文件位置推导模块名；测试里的临时目录回退到旧命名。"""
        src_root = Path(__file__).resolve().parents[2]
        try:
            relative = module_path.relative_to(src_root)
        except ValueError:
            return f"ushareiplay.commands.{command}"
        return ".".join(relative.with_suffix("").parts)

    def load_command_module(self, command):
        """Load command module dynamically"""
        try:
            if command in self.command_modules:
                return self.command_modules[command]

            module_path = next(
                (
                    path
                    for root in self.command_roots
                    if (path := (root / f"{command}.py").resolve()).exists()
                ),
                None,
            )
            if module_path is None:
                self.logger.error(f'module path not exists, {command}.py')
                return None

            package_name = self._module_name(module_path, command)
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
            # 目录声明了哪些模块就加载哪些；没有目录时回退到扫描目录（测试/排查）。
            if self.catalogue is not None:
                command_files = list(self.catalogue.modules())
            else:
                command_files = []
                seen = set()
                for root in self.command_roots:
                    for path in sorted(root.glob('*.py')):
                        if path.stem.startswith('__') or path.stem in seen:
                            continue
                        seen.add(path.stem)
                        command_files.append(path.stem)

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
        definition = self.catalogue.get(command_name) if self.catalogue else None
        module = self.load_command_module(
            definition.module if definition else command_name
        )
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
            return await self._dispatch_command().execute(
                command, message_info, command_info
            )
        except InsufficientCommandLevel as error:
            text = (
                f"需要等级 {error.required_level} 才能使用此命令，"
                f"您当前等级为 {error.user_level}"
            )
            return self._gate_error(text, message_info, command_info, unknown_party_id=True)
        except SleepBlocked:
            return self._gate_error(
                "休息中（11pm-6am）", message_info, command_info, unknown_party_id=True
            )
        except GuestRoomRestricted:
            return self._gate_error(
                "当前处于他人房间，仅支持点歌功能，群管理功能已禁用",
                message_info,
                command_info,
                unknown_party_id=False,
            )
        except Exception:
            self.logger.error(f"Error processing command {command_info}: {traceback.format_exc()}")
            return f"Error processing command {command_info}"

    def _dispatch_command(self) -> DispatchCommand:
        config = self.handler.config if self.handler is not None else None
        return DispatchCommand(
            policy=RolePolicy(config),
            catalogue=self.catalogue,
            users=self._users,
            runtime=self.runtime,
            clock=self._clock,
            silence=command_silence,
            sleep=self._sleep,
            room=self.room_state,
            logger=self.logger,
        )

    def _gate_error(self, text, message_info, command_info, *, unknown_party_id: bool):
        parameters = command_info["parameters"]
        result = {"error": text}
        format_kwargs = {"user": message_info.nickname, **result}
        if unknown_party_id:
            format_kwargs["party_id"] = parameters[0] if parameters else "unknown"
        elif parameters:
            format_kwargs["party_id"] = parameters[0]
        return command_info.get("error_template", "{error}").format(**format_kwargs)

    def is_valid_command(self, content):
        """Check if content is a valid command"""
        if not self.catalogue:
            self.logger.error("Command parser not initialized")
            return False
        return self.catalogue.resolve(content) is not None

    def parse_command(self, content):
        """Parse command content"""
        if not self.catalogue:
            self.logger.error("Command parser not initialized")
            return None
        invocation = self.catalogue.resolve(content)
        return invocation.command_info if invocation else None

    async def execute_runtime_queue_messages(self, queue_messages, send_screen_message=None):
        """排空 runtime 队列，按各自文法把消息交给命令执行。

        队列里混着两文法，drainer 不替它们做统一：

        - **intake 来源**（屏幕扫描 / 回溯补漏）已经由 `classify_chat_line`
          分类完毕，元数据齐全。它们直接交给 `execute_intake_batch` 这条
          intake 接缝，不再套用 queue 文法 —— 否则 `:play a;b` 会在第一个
          `;` 处被截断，`quoted_text` 也会在重建消息时丢掉。
        - **queue 文法来源**（定时器、礼物感谢、console / agent 输入）送来的
          是裸文本，`;` 拆分与 `{user_name}` 替换正是它们要的，照旧走
          `route_queue_text`。

        drainer 按队列顺序逐条调用本方法，两种来源各自保留自己的文法规则。

        Returns:
            本次路由出去执行的命令条数（不是成功条数）。
        """
        command_messages = []
        intake_messages = []
        for message_info in queue_messages:
            if getattr(message_info, "intake_classified", False):
                intake_messages.append(message_info)
                continue

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

        routed_count = 0
        if command_messages:
            await self.execute_command_messages(command_messages)
            routed_count += len(command_messages)

        if intake_messages:
            # 队列只带走批次的命令部分：`items` 在扫描现场就已消费掉，这里
            # 交回的正是同一批命令消息，metadata 原样带着。
            await self.execute_intake_batch(MessageBatch(commands=tuple(intake_messages)))
            routed_count += len(intake_messages)

        return routed_count

    async def execute_intake_batch(self, batch: MessageBatch) -> int:
        """执行一批已经分类好的命令消息（intake 接缝）。

        接收 `MessageBatch` 而不是原始聊天行：分类已经在 `MessageManager` 里做完，
        这里直接消费 `batch.commands`，既不重复解析原始行，也不重新推导触发符
        语义 —— `silent` / `private_reply` / `quoted_text` 随消息一起过来。

        生产路径同样走这里：`execute_runtime_queue_messages` 把队列里 intake
        来源的消息重新收成一个 `MessageBatch` 交回来，因此这条接缝不是只有测试
        才会用到的入口。

        Returns:
            实际执行成功的命令数。
        """
        if not batch.commands:
            return 0

        return await self.execute_command_messages(list(batch.commands))

    async def execute_command_messages(self, messages):
        """
        处理消息中的命令

        消息由 Chat Intake 分类后带元数据过来（intake 接缝 / runtime 队列）：
        `silent` / `private_reply` 直接读消息上的判定结果，不再拿原文重新推断
        前缀语义。`normalize_command_text` 只做一件事 —— 剥掉触发符，让内容能
        匹配 `config.yaml` 里不带触发符的命令前缀（`play` 而不是 `:play`），
        它不再参与静默 / 私聊的判定。
        """
        success_count = 0

        if not messages:
            return success_count

        # Iterate through message info objects
        for message_info in messages:
            if not message_info.content:
                continue

            silent = bool(getattr(message_info, "silent", False))
            content = normalize_command_text(message_info.content)
            if not content:
                continue

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
                        # 私聊回复要经抽屉会话进出，因此这条出口是异步的（#435）。
                        await self.message_dispatch.send_for_message_info(
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

    def get_command_modules(self):
        """获取所有已加载的命令模块。

        用户事件分发自 #436 起不再遍历这里 —— 事件走 `UserEventHooks` 直接路由，
        座位复核是显式调用。保留本方法是因为它仍是公开的模块清单接口（外部排查 /
        工具脚本读它），`self.command_modules` 本身也仍由加载器维护。
        """
        return self.command_modules

    async def notify_user_leave(self, username: str):
        """
        Notify all commands when a user leaves.

        全分身离线判定、canonical 主账号名解析与记忆沉淀调度都已下沉到
        `UserEventHooks.fire(EXIT, ...)`（#429）：只有当该用户的全部分身都不在
        在线列表里时才会触发，且一律以主账号名下发。

        Args:
            username: Username of the user who left
        """
        await self.user_event_hooks.fire(EXIT, username)

    async def _check_seats_on_entry(self, username: str, event_label: str):
        """用户进入/返回派对时复核**座位**（#436 从 `:seat` 的反射钩子提上来）。

        这不是用户事件钩子，是副作用订阅者：`:enter` / `:return` 只会把用户配置的
        命令投进队列，谁都不会顺带看一眼座位。因此座位复核必须显式调，否则删掉
        反射分发后进入/返回时的座位检查会**静默**停掉 —— 没有报错，只是座位再也不
        自动认领。反射分发本身不会回来：#436 已删掉按属性名找钩子的那条路径，
        再挂回去等于把它原样恢复。

        下面的 `SeatManager` 是延迟导入，**环的另一端是 `SeatObservationManager`**：
        它为了触发专注人数联动，在 `seat_manager/seat_observation.py` 里反过来延迟
        导入 `CommandManager` 并调 `notify_focus_count_change`（ADR-0009 §4：懒加载
        严格限定于真循环依赖）。两侧因此都不能在模块顶层互相 import。

        他人房间（`RoomState.in_guest_room()`）不碰座位；异常在这里就地吞掉并记日志 ——
        一个用户的座位复核失败不该带崩整条事件链。
        """
        if self.room_state is not None and self.room_state.is_guest_room:
            return
        try:
            from ushareiplay.managers.seat_manager import SeatManager

            await SeatManager.instance().check_seats_on_entry(username)
        except Exception:
            self.logger.error(f"Error checking seats on {event_label}: {traceback.format_exc()}")

    async def notify_user_enter(self, username: str):
        """
        Notify when a user enters

        该用户配置的进入命令由 UserEventHooks 统一入队；座位复核是显式调用，不走
        属性名分发（#436）。

        Args:
            username: Username of the user who entered
        """
        try:
            if self.user_memory is not None:
                self.user_memory.schedule_user(username)
        except Exception:
            self.logger.warning(f"Failed to schedule memory consolidation for user_enter '{username}'")

        await self.user_event_hooks.fire(ENTER, username)
        await self._check_seats_on_entry(username, "user_enter")

    async def notify_user_return(self, username: str):
        """
        Notify when a user returns（用户重新打开 app 返回派对）

        该用户配置的返回命令由 UserEventHooks 统一入队（入队而非直接执行，队列在
        drain 时才展开 `{user_name}` 宏）。座位复核同样提为显式调用（#436）。

        Args:
            username: Username of the user who returned
        """
        try:
            if self.user_memory is not None:
                self.user_memory.schedule_user(username)
        except Exception:
            self.logger.warning(f"Failed to schedule memory consolidation for user_return '{username}'")

        await self.user_event_hooks.fire(RETURN, username)
        await self._check_seats_on_entry(username, "user_return")

    async def notify_gift_receive(self, username: str):
        """
        Notify when a gift or heat contribution is received

        该用户配置的收礼物命令由 UserEventHooks 统一入队。刻意**不**调度记忆整合
        —— 与 notify_user_return 的差异是历史有意为之，不要"顺手修好"。

        Args:
            username: Username of the user who sent the gift
        """
        await self.user_event_hooks.fire(RECEIVE, username)

    async def notify_focus_count_change(
        self,
        before: int | None,
        after: int,
        changed_users: list[str] | None = None,
        seat_info: dict | None = None,
    ):
        """
        Notify when 专注人数 (focus_count / tvStudyRoomDesc) or seats change.

        `changed_users` 的三态原样透传给 `fire`，**不可归一**：
        - `None` = 触发者未知，回退为所有已配置用户的联动命令；
        - `[]`   = 本次没有用户变更，一条都不发；
        - `[...]` = 只发名单里这些人的。

        Args:
            before: Previous parsed count, or None on first observation
            after: New parsed count
            changed_users: Specific users whose seat/focus status changed, or None for all
            seat_info: Optional dictionary mapping username to seat details
        """
        await self.user_event_hooks.fire(
            FOCUS,
            ctx={"before": before, "after": after, SEAT_INFO_CTX_KEY: seat_info or {}},
            usernames=changed_users,
        )
