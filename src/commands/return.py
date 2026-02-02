"""
用户返回命令 - 配置用户返回派对时自动执行的命令

与 enter 命令逻辑一致，支持数据库配置返回事件行为。
当用户重新打开 app 返回派对时（服务器保留会话的“返回”场景）触发。
"""
import traceback
import shlex
from ..core.base_command import BaseCommand
from ..dal.return_dao import ReturnDao


def create_command(controller):
    return_cmd = ReturnCommand(controller)
    controller.return_command = return_cmd
    return return_cmd


command = None


class ReturnCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    async def process(self, message_info, parameters):
        """Process return command

        Args:
            message_info: MessageInfo object
            parameters: List of parameters

        Returns:
            dict: Result with success message or error
        """
        try:
            try:
                original_content = message_info.content
                parts = original_content.split(None, 1)
                if len(parts) < 2:
                    return {'error': '缺少参数。使用: :return [add|del|list|clear]'}

                params = shlex.split(parts[1])
            except ValueError:
                return {'error': '参数格式错误，带空格的参数请使用引号包裹'}

            if not params:
                return {'error': '缺少参数。使用: :return [add|del|list|clear]'}

            operation = params[0]
            username = message_info.nickname

            if operation == 'add':
                if len(params) < 2:
                    return {'error': '缺少命令内容。使用: :return add "命令内容"'}

                cmd_text = params[1]
                if not cmd_text.startswith(':'):
                    return {'error': '命令必须以冒号(:)开头，例如 ":play 歌曲名"'}

                await ReturnDao.create(username, cmd_text)
                return {'message': f'已添加返回命令: {cmd_text}'}

            elif operation == 'del':
                if len(params) < 2:
                    return {'error': '缺少命令ID。使用: :return del <id>'}

                try:
                    command_id = int(params[1])
                except ValueError:
                    return {'error': '命令ID必须是数字'}

                deleted = await ReturnDao.delete_by_id(command_id)
                if deleted:
                    return {'message': f'已删除命令 ID: {command_id}'}
                return {'error': f'未找到命令 ID: {command_id}'}

            elif operation == 'list':
                commands = await ReturnDao.get_by_username(username)
                if not commands:
                    return {'message': '您还没有设置任何返回命令'}

                message_lines = ['您的返回命令列表:']
                for cmd in commands:
                    message_lines.append(f'  [{cmd.id}] {cmd.command}')
                return {'message': '\n'.join(message_lines)}

            elif operation == 'clear':
                count = await ReturnDao.delete_all_by_username(username)
                if count > 0:
                    return {'message': f'已清除 {count} 个返回命令'}
                return {'message': '您没有任何返回命令需要清除'}

            else:
                return {'error': f'未知操作: {operation}。使用: :return [add|del|list|clear]'}

        except Exception as e:
            self.handler.log_error(f"Error processing return command: {traceback.format_exc()}")
            return {'error': '处理返回命令时出错'}

    async def user_return(self, username: str):
        """用户返回派对时调用（与 user_enter 逻辑一致，从数据库读取并执行该用户的返回命令）"""
        try:
            commands = await ReturnDao.get_by_username(username)
            if not commands:
                return

            self.handler.logger.info(f"User {username} returned, executing {len(commands)} return command(s)")

            from ..core.message_queue import MessageQueue
            from ..models.message_info import MessageInfo

            message_queue = MessageQueue.instance()
            for cmd in commands:
                message_info = MessageInfo(
                    content=cmd.command,
                    nickname=username
                )
                await message_queue.put_message(message_info)
                self.handler.logger.info(f"Queued return command [{cmd.id}] for {username}: {cmd.command}")

        except Exception as e:
            self.handler.log_error(f"Error in return user_return: {traceback.format_exc()}")
