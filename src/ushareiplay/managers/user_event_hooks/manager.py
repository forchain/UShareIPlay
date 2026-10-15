"""用户事件钩子引擎：命令侧解析与渲染、事件侧入队。"""

import logging
import shlex
import traceback
from typing import List, Optional

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.registry import COMMAND_PREFIXES, spec_for
from ushareiplay.models.message_info import MessageInfo


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
    ) -> int:
        """事件发生：把该用户配置的钩子命令投进运行时队列。

        Args:
            event_type: 事件类型。
            username: 触发用户（UI 侧可见名，由调用方负责命名域解析）。`None` 表示
                「触发者未知」，回退为该事件类型下所有已配置用户的命令 —— 这是专注
                人数联动的向后兼容路径。注意它与「明确传入空名单」不是一回事：空名单
                表示没有用户变更，应当一条都不发。
            ctx: 事件的实时上下文（专注人数前后值等），只用于日志。

        Returns:
            int: 实际入队的命令条数。
        """
        spec = spec_for(event_type)
        ctx = ctx or {}

        try:
            if username is None:
                commands = await UserEventHookDAO.get_all_ordered(event_type)
            else:
                commands = await UserEventHookDAO.get_by_username(event_type, username)

            if not commands:
                return 0

            queue = MessageQueue.instance()
            queued = 0
            for cmd in commands:
                # 入队而不是直接执行：队列在 drain 时才展开 `{user_name}` 宏，
                # 绕过队列会悄悄丢掉这个宏。
                target = username if username is not None else cmd.user.username
                await queue.put_message(MessageInfo(content=cmd.command, nickname=target))
                queued += 1

            scope = username if username is not None else "全部用户"
            self._log_info(
                f"{spec.noun}触发 (ctx={ctx or '无'}), 为 {scope} 入队 {queued} 条命令"
            )
            return queued
        except Exception:
            self._log_error(f"Error in UserEventHooks.fire: {traceback.format_exc()}")
            return 0
