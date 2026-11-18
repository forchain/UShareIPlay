import shlex

from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.shared.roles import RolePolicy
from ushareiplay.modules.user.domain import (
    InvalidLevelError,
    MissingCallerError,
    NewLevelNotBelowCallerError,
    TargetNotBelowCallerError,
)
from ushareiplay.modules.user.use_cases import GetLevel, SetLevel


class LevelCommand(BaseCommand):
    error_message = '处理等级命令失败: {error}'

    def _role_policy(self) -> RolePolicy:
        return RolePolicy(self.controller.config)

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

        caller_nickname = message_info.nickname if message_info else ''
        users = TortoiseUserRepository()

        # 模式 1: 无参数 - 显示当前用户等级
        if len(params) == 0:
            if not caller_nickname:
                return {'error': '无法获取当前用户信息'}
            user = await GetLevel(users).execute(caller_nickname)
            return {'message': f'您当前等级为 L{user.level}'}

        target_username = params[0].strip()

        # 模式 2: 1 个参数 - 查看指定用户的等级
        if len(params) == 1:
            if not target_username:
                return {'error': '昵称不能为空'}
            target_user = await GetLevel(users).execute(target_username)
            return {'message': f'用户 {target_user.username} 的等级为 L{target_user.level}'}

        # 模式 3: 2 个参数 - 设置指定用户的等级
        if len(params) == 2:
            if not target_username:
                return {'error': '昵称不能为空'}

            try:
                new_level = int(params[1].strip())
            except ValueError:
                return {'error': '等级必须为 0-9 的整数'}

            try:
                target_user = await SetLevel(users, self._role_policy()).execute(
                    caller_nickname, target_username, new_level
                )
            except InvalidLevelError:
                return {'error': '等级必须为 0-9 的整数'}
            except MissingCallerError:
                return {'error': '权限不足：无法验证操作者身份'}
            except TargetNotBelowCallerError as error:
                return {
                    'error': f'权限不足：只能修改等级低于自己的用户（目标当前等级 L{error.target_level}，您当前等级 L{error.caller_level}）'
                }
            except NewLevelNotBelowCallerError as error:
                return {
                    'error': f'权限不足：设置的目标等级（L{error.new_level}）必须低于您的等级（L{error.caller_level}）'
                }

            return {'message': f'已将用户 {target_user.username} 的等级设置为 L{new_level}'}

        return {'error': '参数过多。用法: :level [用户名] [等级]'}
