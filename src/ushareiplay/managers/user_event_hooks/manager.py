"""用户事件钩子引擎：命令侧解析与渲染、事件侧入队。"""

import logging
import shlex
import traceback
from typing import Iterable, List, Optional

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.gates import GATES
from ushareiplay.managers.user_event_hooks.registry import COMMAND_PREFIXES, spec_for
from ushareiplay.models.message_info import MessageInfo


def _scalar_ctx(ctx: dict) -> dict:
    """日志里只留标量上下文字段。

    座位观测 `seat_info` 那种嵌套数据不进运行时日志：座位观测是轮询路径，把整张
    观测表打进日志就是监控刷屏。
    """
    return {k: v for k, v in ctx.items() if isinstance(v, (str, int, float, bool))}


class UserEventHooks(Singleton):
    """用户事件钩子的两个入口：配置 CRUD 与事件触发。

    命令层只调 `execute_crud`，事件层只调 `fire`；两者都不知道 shlex、命令前缀
    规则或五张表长什么样。
    """

    def __init__(self, handler=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)

    @property
    def handler(self):
        return self._handler

    def _log_info(self, message: str):
        (self._logger or logging.getLogger("user_event_hooks")).info(message)

    def _log_error(self, message: str):
        logger = self._logger or logging.getLogger("user_event_hooks")
        if hasattr(self._handler, "log_error"):
            self._handler.log_error(message)
        else:
            logger.error(message)

    def _log_warning(self, message: str):
        (self._logger or logging.getLogger("user_event_hooks")).warning(message)

    async def execute_crud(self, event_type: str, username: str, raw_content: str) -> dict:
        """执行一条 `:enter` / `:exit` / `:return` / `:receive` / `:focus` 配置命令。

        Args:
            event_type: 事件类型，决定模型与全部文案。
            username: 配置归属的用户（DB 侧用 canonical 名）。
            raw_content: 消息原文。必须传原文而不是预切好的参数列表 —— 引号包裹的
                带空格命令只有在原文上做 shlex 才能还原。

        Returns:
            dict: `{'message': ...}` 或 `{'error': ...}`。
        """
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

            await UserEventHookDAO.create(event_type, username, command)
            self._log_info(f"{username} 新增{spec.noun}: {command}")
            return {"message": f"已添加{spec.noun}: {command}"}

        if operation == "del":
            if len(params) < 2:
                return {"error": f"缺少命令ID。使用: {spec.prefix} del <id>"}

            try:
                command_id = int(params[1])
            except ValueError:
                return {"error": "命令ID必须是数字"}

            if await UserEventHookDAO.delete_by_id(event_type, command_id):
                self._log_info(f"{username} 删除{spec.noun} ID: {command_id}")
                return {"message": f"已删除命令 ID: {command_id}"}
            return {"error": f"未找到命令 ID: {command_id}"}

        if operation == "list":
            commands = await UserEventHookDAO.get_by_username(event_type, username)
            if not commands:
                return {"message": f"您还没有设置任何{spec.noun}"}

            lines = [f"您的{spec.noun}列表:"]
            lines.extend(f"  [{cmd.id}] {cmd.command}" for cmd in commands)
            return {"message": "\n".join(lines)}

        if operation == "clear":
            count = await UserEventHookDAO.delete_all_by_username(event_type, username)
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

        选人分三态，**不可合并** —— 合并就是一次静默的行为变更：

        - `username` / `usernames` 都为 `None`：触发者未知，向后兼容地回退为该事件
          类型下所有已配置用户的命令（专注人数联动的旧调用路径）；
        - `usernames == []`：没有用户变更，一条都不发；
        - 给了名单：只发这些人的命令。

        Args:
            event_type: 事件类型。
            username: 单个触发用户（进入 / 离开 / 返回 / 收礼物用它；由调用方负责
                命名域解析）。批量触发请用 `usernames`，别把名单塞进这个参数 ——
                那样会被显式拒绝而不是被当成单用户查询。
            ctx: 事件的实时上下文（专注人数前后值、座位观测等）。宏策略从这里取数据，
                见 `registry.MacroExpander`；它不影响「发给谁」。
            usernames: 触发者名单，只用于按名单隔离（座位 / 专注人数联动）。

        Returns:
            int: 实际入队的命令条数。被事件闸门拦下时返回 0。
        """
        spec = spec_for(event_type)
        ctx = ctx or {}

        try:
            # 事件闸门（`gates.py`）：判断这次事件该不该触发，并把触发者解析成规范名。
            # 「离开」事件的闸门会检查该用户的全部分身是否都已离线；没有闸门的事件类型
            # 拿到原样的 username，行为与收拢前一致。闸门只作用于「单用户」触发。
            gate = GATES.get(event_type)
            gated = False
            trigger = username
            if gate is not None and username is not None:
                trigger = await gate(
                    username, log_info=self._log_info, log_warning=self._log_warning
                )
                if trigger is None:
                    return 0
                gated = True

            if gated:
                # 闸门已经决定触发并给出了规范名，名单就是它自己。
                targets: Optional[List[str]] = [trigger]
            else:
                targets = self._resolve_targets(username, usernames)

            if targets is not None and not targets:
                # 空名单是「没有用户变更」，与「触发者未知」语义相反，一条都不发。
                return 0

            if targets is None:
                commands = await UserEventHookDAO.get_all_ordered(event_type)
            else:
                commands = await self._collect_commands(event_type, targets)

            if not commands:
                return 0

            expander = spec.macros
            queue = MessageQueue.instance()
            queued = 0
            for cmd in commands:
                owner = cmd.user.username
                text = cmd.command
                if expander is not None:
                    text = await expander(text, owner, ctx)
                # 入队而不是直接执行：队列在 drain 时才展开 `{user_name}` 宏，
                # 绕过队列会悄悄丢掉这个宏。
                # 单用户触发时沿用触发者名（经闸门时已是规范名）；名单 / 全量触发时用
                # 钩子归属人。
                await queue.put_message(
                    MessageInfo(
                        content=text,
                        nickname=trigger if trigger is not None else owner,
                    )
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

    @staticmethod
    def _resolve_targets(
        username: Optional[str], usernames: Optional[Iterable[str]]
    ) -> Optional[List[str]]:
        """把「单用户 / 名单 / 触发者未知」三态归一成触发者名单。

        Returns:
            list[str] | None: `None` 表示触发者未知（回退为全部用户）；空 list 表示
            没有人变更（一条都不发）。

        Raises:
            ValueError: 同时给了 `username` 与 `usernames`，语义冲突。
            TypeError: `username` 不是单个用户名 —— 名单塞进单值参数会被误当成
                「查一个叫这个的用户」，必须显式拒绝而不是猜。
        """
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

    @staticmethod
    async def _collect_commands(event_type: str, targets: List[str]) -> list:
        """按名单取命令，按 `cmd.id` 去重。

        去重是必需的：同一主账号的多个分身都在名单里时，`get_by_username` 解析到
        主账号那同一批行，不去重就会把同一条命令入队两次。
        """
        commands = []
        seen_cmd_ids = set()
        for target in targets:
            for cmd in await UserEventHookDAO.get_by_username(event_type, target):
                if cmd.id not in seen_cmd_ids:
                    seen_cmd_ids.add(cmd.id)
                    commands.append(cmd)
        return commands
