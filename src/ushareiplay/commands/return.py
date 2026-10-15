"""
`:return` 命令：用户事件钩子深度模块的薄适配器。

当用户重新打开 app 返回派对时（服务器保留会话的“返回”场景）触发该用户配置的
返回命令。shlex 解析、前缀校验与全部文案都在 `UserEventHooks` 内部。
"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.user_event_hooks import RETURN, UserEventHooks


class ReturnCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理返回命令时出错'

    async def do_process(self, message_info, parameters):
        """配置用户返回派对时要执行的命令。解析与渲染都在 UserEventHooks 内部。"""
        return await UserEventHooks.instance().execute_crud(
            RETURN, message_info.nickname, message_info.content
        )

    async def user_return(self, username: str):
        """用户返回派对时，把该用户配置的返回命令投进队列。

        方法保留：它是命令层的事件接缝，测试直接调它断言入队结果。生产触发不再走
        按属性名分发（#436 已删）—— `CommandManager.notify_user_return` 直接调
        `UserEventHooks.fire`。
        """
        await UserEventHooks.instance().fire(RETURN, username)
