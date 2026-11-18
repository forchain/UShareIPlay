"""`:receive` 命令：用户事件钩子引擎的薄适配器。

当用户送礼或投喂热度时触发该用户配置的收礼物命令。注意收礼物命令按 alias-group
解析用户（主账号配置的命令对其任意分身都生效），这条口径由注册表声明。
"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.room.registry import RECEIVE


class ReceiveCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理收礼物命令时出错'

    def __init__(self, controller):
        super().__init__(controller)
        self.user_event_hooks = controller.user_event_hooks

    async def do_process(self, message_info, parameters):
        """配置收到礼物时要执行的命令。解析与渲染都在引擎内部。"""
        return await self.user_event_hooks.execute_crud(
            RECEIVE, message_info.nickname, message_info.content
        )

    async def user_gift_receive(self, username: str):
        """用户送礼或投喂热度时，把该用户配置的收礼物命令投进队列。"""
        await self.user_event_hooks.fire(RECEIVE, username)
