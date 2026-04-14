import shlex
import traceback

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.dal.user_dao import UserDAO


def create_command(controller):
    alias_command = AliasCommand(controller)
    controller.alias_command = alias_command
    return alias_command


command = None


class AliasCommand(BaseCommand):
    async def process(self, message_info, parameters):
        """
        Bind an alias username to a canonical username.

        Usage:
          :alias "<alias username>" "<canonical username>"
        """
        try:
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

            # Create/fetch alias record WITHOUT canonical resolution
            alias_user = await UserDAO.get_or_create_raw(alias_username)

            # Canonical target should always resolve to final canonical user
            canonical_user = await UserDAO.get_or_create(canonical_username)

            if alias_user.id == canonical_user.id:
                return {'error': '别名与原始用户不能相同'}

            alias_user.canonical_user_id = canonical_user.id
            await alias_user.save(update_fields=["canonical_user_id"])

            return {
                'message': f'已绑定别名 "{alias_username}" → "{canonical_user.username}" (id={canonical_user.id})'
            }
        except Exception:
            self.soul_handler.logger.error(f"Error in alias command: {traceback.format_exc()}")
            return {'error': '处理失败'}

