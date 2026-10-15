"""`:enter` 命令：用户事件钩子深度模块的薄适配器（#422 示踪弹）。"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.user_event_hooks import ENTER, UserEventHooks


class EnterCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理进入命令时出错'

    async def do_process(self, message_info, parameters):
        """配置进入房间时要执行的命令。解析与渲染都在 UserEventHooks 内部。"""
        return await UserEventHooks.instance().execute_crud(
            ENTER, message_info.nickname, message_info.content
        )

    async def user_enter(self, username: str):
        """有人进入派对：把他配置的进入命令投进队列。

        方法名保留是因为 CommandManager 按属性名分发；实现已全部下沉到
        UserEventHooks。
        """
        await UserEventHooks.instance().fire(ENTER, username)
