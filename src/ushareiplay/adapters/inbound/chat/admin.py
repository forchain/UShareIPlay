"""房管命令：薄适配器，把参数解析之外的一切交给 manage-admin 用例。

命名域解析（canonical 名 -> 分身名）内置在抽屉会话里，命令层不再解析一次。
房管名单的规则失败以命名异常从用例抛出，这里只把它们翻成既有的聊天原话。
"""
import shlex

from ushareiplay.adapters.inbound.chat.base_command import BaseCommand
from ushareiplay.modules.room.domain import AlreadyRoomAdmin, NotRoomAdmin


class AdminCommand(BaseCommand):
    error_message = '{error}'

    async def do_process(self, message_info, parameters):
        """处理管理员邀请/解除。参数：:admin [1|0] [昵称]，未指定昵称则操作自己。"""
        try:
            params = shlex.split(' '.join(parameters))
        except ValueError:
            return {'error': 'Invalid parameters format. Please check quotes.', 'user': message_info.nickname}

        if len(params) < 1:
            return {'error': 'Missing parameter. Use: :admin [1|0] [昵称]', 'user': message_info.nickname}

        try:
            enable = int(params[0]) == 1
        except ValueError:
            return {'error': 'Invalid parameter. Use: :admin [1|0] [昵称]', 'user': message_info.nickname}

        # 目标名原样交下去：canonical 名（主账号）与分身名都能进流程。
        target_nickname = params[1].strip() if len(params) > 1 and params[1].strip() else message_info.nickname

        try:
            return await self.controller.manage_admin.manage_admin(enable, target_nickname)
        except AlreadyRoomAdmin as error:
            return {'error': '你已经是管理员了', 'user': error.user}
        except NotRoomAdmin as error:
            return {'error': '你还不是管理员', 'user': error.user}
