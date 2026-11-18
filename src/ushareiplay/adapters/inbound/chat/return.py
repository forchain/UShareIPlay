"""`:return` 命令：用户事件钩子引擎的薄适配器。

当用户重新打开 app 返回派对时（服务器保留会话的“返回”场景）触发该用户配置的
返回命令。
"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.room.registry import RETURN


class ReturnCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理返回命令时出错'

    def __init__(self, controller):
        super().__init__(controller)
        self.user_event_hooks = controller.user_event_hooks

    async def do_process(self, message_info, parameters):
        """配置用户返回派对时要执行的命令。解析与渲染都在引擎内部。"""
        return await self.user_event_hooks.execute_crud(
            RETURN, message_info.nickname, message_info.content
        )

    async def user_return(self, username: str):
        """用户返回派对时，把该用户配置的返回命令投进队列。"""
        await self.user_event_hooks.fire(RETURN, username)
