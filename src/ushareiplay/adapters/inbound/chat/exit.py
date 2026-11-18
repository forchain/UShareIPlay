"""`:exit` 命令：用户事件钩子引擎的薄适配器（与 `:enter` 同形）。"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.room.registry import EXIT


class ExitCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理离开命令时出错'

    def __init__(self, controller):
        super().__init__(controller)
        self.user_event_hooks = controller.user_event_hooks

    async def do_process(self, message_info, parameters):
        """配置离开派对时要执行的命令。解析与渲染都在引擎内部。"""
        return await self.user_event_hooks.execute_crud(
            EXIT, message_info.nickname, message_info.content
        )

    async def user_leave(self, username: str):
        """有人离开派对：把他配置的离开命令投进队列。

        多分身离线判定与主账号名解析都在 `fire()` 里完成 —— 到这里触发时，
        `username` 已是 canonical 主账号名。
        """
        await self.user_event_hooks.fire(EXIT, username)
