"""`:exit` 命令：用户事件钩子深度模块的薄适配器（与 `:enter` 同形）。"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.user_event_hooks import EXIT, UserEventHooks


class ExitCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理离开命令时出错'

    async def do_process(self, message_info, parameters):
        """配置离开派对时要执行的命令。解析与渲染都在 UserEventHooks 内部。"""
        return await UserEventHooks.instance().execute_crud(
            EXIT, message_info.nickname, message_info.content
        )

    async def user_leave(self, username: str):
        """有人离开派对：把他配置的离开命令投进队列。

        方法名保留是因为 CommandManager 按属性名分发；实现已全部下沉到
        UserEventHooks。多分身离线判定与主账号名解析也在那里面完成 —— 到这里
        触发时，`username` 已是 canonical 主账号名。
        """
        await UserEventHooks.instance().fire(EXIT, username)
