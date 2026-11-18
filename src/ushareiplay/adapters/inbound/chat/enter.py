"""`:enter` 命令：用户事件钩子引擎的薄适配器。"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.room.registry import ENTER


class EnterCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理进入命令时出错'

    def __init__(self, controller):
        super().__init__(controller)
        self.user_event_hooks = controller.user_event_hooks

    async def do_process(self, message_info, parameters):
        """配置进入房间时要执行的命令。解析与渲染都在引擎内部。"""
        return await self.user_event_hooks.execute_crud(
            ENTER, message_info.nickname, message_info.content
        )

    async def user_enter(self, username: str):
        """有人进入派对：把他配置的进入命令投进队列。"""
        await self.user_event_hooks.fire(ENTER, username)
