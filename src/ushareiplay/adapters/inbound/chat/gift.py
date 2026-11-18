"""送礼命令：薄适配器，把参数解析之外的一切交给 `UserProfileActions.send_gift`。"""

from ushareiplay.core.base_command import BaseCommand


class GiftCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '送礼失败: {error}'

    async def do_process(self, message_info, parameters):
        """取目标昵称后原样交给送礼流程：canonical 名或分身名都可以。"""
        if parameters and parameters[0].strip():
            target_nickname = parameters[0].strip()
        else:
            target_nickname = message_info.nickname

        return await self.controller.user_profile_actions.send_gift(target_nickname)
