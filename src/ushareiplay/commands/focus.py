"""`:focus` 命令：用户事件钩子深度模块的薄适配器（#433 示踪弹）。

解析与渲染都在 `UserEventHooks` 内部；这里只做参数转译。
"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.user_event_hooks import FOCUS, UserEventHooks
from ushareiplay.managers.user_event_hooks.macros import SEAT_INFO_CTX_KEY


class FocusCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理专注人数命令时出错'

    async def do_process(self, message_info, parameters):
        """配置专注人数 / 座位联动时要执行的命令。解析与渲染都在 UserEventHooks 内部。"""
        return await UserEventHooks.instance().execute_crud(
            FOCUS, message_info.nickname, message_info.content
        )

    async def focus_count_change(
        self,
        before: int | None,
        after: int,
        changed_users: list[str] | None = None,
        seat_info: dict | None = None,
    ):
        """专注人数变化或特定用户**座位**变动时执行。

        方法名保留是因为 CommandManager 按属性名分发；方法体只剩参数转译：选人、
        `{username}` / `{seat}` / `{action}` 宏展开与入队都在 UserEventHooks 内部。

        Args:
            before: 上一次读到的人数，首次观测为 `None`。
            after: 本次读到的人数。
            changed_users: 本次**座位**变更的用户。`None` = 触发者未知，回退为执行
                所有用户的联动命令（用户级隔离的旧路径）；`[]` = 没有用户变更，
                一条都不发。两者语义相反，不可合并。
            seat_info: 本次座位观测，键是 Soul UI 上可见的分身名，值含 `seat_number`
                与 `action`，即 `{seat}` / `{action}` 宏的数据源。
        """
        await UserEventHooks.instance().fire(
            FOCUS,
            usernames=changed_users,
            ctx={"before": before, "after": after, SEAT_INFO_CTX_KEY: seat_info or {}},
        )
