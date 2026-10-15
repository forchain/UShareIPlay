"""房管命令：薄适配器，把参数解析之外的一切交给 `AdminManager.manage_admin`。

#439 起这里不再自己 `resolve_visible_username`（也没有 `info_manager` 快捷方式）：
命名域解析（canonical 名 -> 分身名）已经内置在抽屉会话里，命令层再解析一次等于让
「解析不到就保留原名」这种兜底在两处各活一份，且会把 canonical 名提前改写掉，下游按
canonical 名查库的路径反而失配。
"""
import shlex
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.admin_manager import AdminManager


class AdminCommand(BaseCommand):
    error_message = '{error}'

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

        # 目标名原样交下去：canonical 名（主账号）与分身名都能进流程，解析由抽屉会话负责。
        target_nickname = params[1].strip() if len(params) > 1 and params[1].strip() else message_info.nickname

        return await AdminManager.instance().manage_admin(enable, target_nickname)
