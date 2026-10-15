"""送礼命令：薄适配器，把参数解析之外的一切交给 `UserManager.send_gift`。

#438 起这里不再自己 `resolve_visible_username`：在线用户抽屉这一层的命名域解析
（canonical 名 -> 分身名）已经内置在抽屉会话里，命令层再解析一次，等于让
「解析不到就保留原名」这种兜底在两处各活一份，且会把 canonical 名提前改写掉，
下游按 canonical 名查库的路径反而失配。
"""
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.user_manager import UserManager


class GiftCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '送礼失败: {error}'

    async def do_process(self, message_info, parameters):
        """取目标昵称后原样交给送礼流程：canonical 名或分身名都可以。"""
        if parameters and parameters[0].strip():
            target_nickname = parameters[0].strip()
        else:
            target_nickname = message_info.nickname  # 未指定则送给自己

        return await UserManager.instance().send_gift(target_nickname)
