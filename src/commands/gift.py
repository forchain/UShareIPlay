"""送礼命令：先打开目标用户资料页，再点击送礼物并执行赠送/使用/背包逻辑"""
import traceback

from ..core.base_command import BaseCommand
from ..managers.user_manager import UserManager


def create_command(controller):
    gift_command = GiftCommand(controller)
    controller.gift_command = gift_command
    return gift_command


command = None


class GiftCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    async def process(self, message_info, parameters):
        """处理送礼命令：先打开目标用户资料页，再执行送礼流程"""
        try:
            if not parameters:
                return {'error': '请指定要送礼的对象，例如 :gift 昵称'}

            target_nickname = parameters[0].strip()
            if not target_nickname:
                return {'error': '请指定要送礼的对象，例如 :gift 昵称'}

            return UserManager.instance().send_gift(target_nickname)
        except Exception as e:
            self.handler.log_error(f"送礼命令执行失败: {traceback.format_exc()}")
            return {'error': f'送礼失败: {str(e)}'}
