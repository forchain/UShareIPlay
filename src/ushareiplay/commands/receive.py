"""`:receive` 命令：用户事件钩子深度模块的薄适配器。

当用户送礼或投喂热度时触发该用户配置的收礼物命令。shlex 解析、前缀校验与全部文案
都在 `UserEventHooks` 内部；注意收礼物命令按 alias-group 解析用户（主账号配置的命令
对其任意分身都生效），这条口径由 `registry` 声明。
"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.user_event_hooks import RECEIVE, UserEventHooks


class ReceiveCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理收礼物命令时出错'

    async def do_process(self, message_info, parameters):
        """配置收到礼物时要执行的命令。解析与渲染都在 UserEventHooks 内部。"""
        return await UserEventHooks.instance().execute_crud(
            RECEIVE, message_info.nickname, message_info.content
        )

    async def user_gift_receive(self, username: str):
        """用户送礼或投喂热度时，把该用户配置的收礼物命令投进队列。

        方法保留：它是命令层的事件接缝，测试直接调它断言入队结果。生产触发不再走
        按属性名分发（#436 已删）—— `CommandManager.notify_gift_receive` 直接调
        `UserEventHooks.fire`。
        """
        await UserEventHooks.instance().fire(RECEIVE, username)
