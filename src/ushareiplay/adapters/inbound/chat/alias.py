import shlex

from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.user.domain import AliasCycleError
from ushareiplay.modules.user.use_cases import BindAlias


class AliasCommand(BaseCommand):
    error_message = '处理失败'

    async def do_process(self, message_info, parameters):
        """
        Bind an alias username to a canonical username.

        Usage:
          :alias "<alias username>" "<canonical username>"
        """
        try:
            params = shlex.split(' '.join(parameters))
        except ValueError:
            return {'error': '参数格式错误，带空格的昵称请使用引号包裹'}

        if len(params) < 2:
            return {'error': '缺少参数。用法: :alias "<别名>" "<原始名>"'}

        alias_username = params[0].strip()
        canonical_username = params[1].strip()

        if not alias_username or not canonical_username:
            return {'error': '昵称不能为空。用法: :alias "<别名>" "<原始名>"'}

        try:
            canonical_user = await BindAlias(TortoiseUserRepository()).execute(
                alias_username, canonical_username
            )
        except AliasCycleError:
            return {'error': '别名与原始用户不能相同'}

        return {
            'message': f'已绑定别名 "{alias_username}" → "{canonical_user.username}" (id={canonical_user.id})'
        }
