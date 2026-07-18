"""送礼命令：先打开目标用户资料页，再点击送礼物并执行赠送/使用/背包逻辑"""
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.user_manager import UserManager


class GiftCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '送礼失败: {error}'

    async def do_process(self, message_info, parameters):
        """处理送礼命令：先打开目标用户资料页，再执行送礼流程"""
        if parameters and parameters[0].strip():
            target_nickname = parameters[0].strip()
        else:
            target_nickname = message_info.nickname  # 未指定则送给自己

        return UserManager.instance().send_gift(target_nickname)
