import shlex
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.admin_manager import AdminManager


class AdminCommand(BaseCommand):
    error_message = '{error}'

    def __init__(self, controller):
        super().__init__(controller)
        self.admin_manager = AdminManager.instance()

    async def do_process(self, message_info, parameters):
        """处理管理员邀请/解除。参数：:admin [1|0] [昵称]，未指定昵称则操作自己。昵称可含空格，用引号包裹。"""
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

        target_nickname = params[1].strip() if len(params) > 1 and params[1].strip() else message_info.nickname

        return await self.admin_manager.manage_admin(enable, target_nickname)
