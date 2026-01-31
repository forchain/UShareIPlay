import shlex
import traceback
from ..core.base_command import BaseCommand
from ..managers.admin_manager import AdminManager


def create_command(controller):
    admin_command = AdminCommand(controller)
    controller.admin_command = admin_command
    return admin_command


command = None


class AdminCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.admin_manager = AdminManager.instance()

    async def process(self, message_info, parameters):
        """处理管理员邀请/解除。参数：:admin [1|0] [昵称]，未指定昵称则操作自己。昵称可含空格，用引号包裹。"""
        try:
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
        except Exception as e:
            self.soul_handler.logger.error(f"Error in admin command: {traceback.format_exc()}")
            return {'error': str(e), 'user': message_info.nickname}
