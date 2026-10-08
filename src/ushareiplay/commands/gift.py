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

        # 送礼要在在线列表里点到具体的人，必须用房间里可见的分身名（分身与主账号
        # 在 UI 上是两个名字）；解析不到时保留原名，由下游按身份匹配兜底。
        try:
            target_nickname = await self.info_manager.resolve_visible_username(target_nickname)
        except Exception:
            pass  # 门面不可用时保留原名，由下游按身份匹配兜底

        return await UserManager.instance().send_gift(target_nickname)
