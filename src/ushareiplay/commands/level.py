import shlex

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.dal.user_dao import UserDAO


class LevelCommand(BaseCommand):
    error_message = '处理等级命令失败: {error}'

    def _get_system_users(self) -> set[str]:
        system_users = set()
        if self.soul_handler and hasattr(self.soul_handler, 'config') and isinstance(self.soul_handler.config, dict):
            system_users.update(self.soul_handler.config.get('system_users', []))
        if hasattr(self.controller, 'config') and isinstance(self.controller.config, dict):
            cfg = self.controller.config
            system_users.update(cfg.get('system_users', []))
            if isinstance(cfg.get('soul'), dict):
                system_users.update(cfg['soul'].get('system_users', []))
        if not system_users:
            system_users.update(['Timer', 'Console', 'Agent'])
        return system_users

    async def do_process(self, message_info, parameters):
        """
        查看或设置用户等级。
        用法:
          :level                     - 查看当前用户等级
          :level <用户名>            - 查看指定用户等级
          :level <用户名> <等级>     - 设置指定用户等级
        """
        raw_text = ' '.join(parameters).strip()
        try:
            params = shlex.split(raw_text) if raw_text else []
        except ValueError:
            return {'error': '参数格式错误，带空格的昵称请使用引号包裹'}

        caller_nickname = getattr(message_info, 'nickname', '') if message_info else ''

        # 模式 1: 无参数 - 显示当前用户等级
        if len(params) == 0:
            if not caller_nickname:
                return {'error': '无法获取当前用户信息'}
            user = await UserDAO.get_or_create(caller_nickname)
            return {'message': f'您当前等级为 L{user.level}'}

        # 模式 2: 1 个参数 - 查看指定用户的等级
        if len(params) == 1:
            target_username = params[0].strip()
            if not target_username:
                return {'error': '昵称不能为空'}
            target_user = await UserDAO.get_or_create(target_username)
            return {'message': f'用户 {target_user.username} 的等级为 L{target_user.level}'}

        # 模式 3: 2 个参数 - 设置指定用户的等级
        if len(params) == 2:
            target_username = params[0].strip()
            level_str = params[1].strip()

            if not target_username:
                return {'error': '昵称不能为空'}

            try:
                new_level = int(level_str)
                if new_level < 0 or new_level > 9:
                    return {'error': '等级必须为 0-9 的整数'}
            except ValueError:
                return {'error': '等级必须为 0-9 的整数'}

            system_users = self._get_system_users()
            is_system_user = caller_nickname in system_users

            target_user = await UserDAO.get_or_create(target_username)

            if not is_system_user:
                if not caller_nickname:
                    return {'error': '权限不足：无法验证操作者身份'}

                caller_user = await UserDAO.get_or_create(caller_nickname)

                # 规则 1: 只能修改当前等级低于自己的用户
                if target_user.level >= caller_user.level:
                    return {
                        'error': f'权限不足：只能修改等级低于自己的用户（目标当前等级 L{target_user.level}，您当前等级 L{caller_user.level}）'
                    }

                # 规则 2: 设置的目标等级必须低于自己的等级
                if new_level >= caller_user.level:
                    return {
                        'error': f'权限不足：设置的目标等级（L{new_level}）必须低于您的等级（L{caller_user.level}）'
                    }

            # 执行等级更新（target_user 已被 UserDAO.get_or_create 解析为 canonical user）
            target_user.level = new_level
            await target_user.save(update_fields=['level'])

            return {'message': f'已将用户 {target_user.username} 的等级设置为 L{new_level}'}

        return {'error': '参数过多。用法: :level [用户名] [等级]'}
