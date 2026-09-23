import traceback
import shlex
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.dal.receive_dao import ReceiveDao


class ReceiveCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理收礼物命令时出错'

    async def do_process(self, message_info, parameters):
        """Process receive command

        Args:
            message_info: MessageInfo object
            parameters: List of parameters

        Returns:
            dict: Result with success message or error
        """
        try:
            original_content = message_info.content
            parts = original_content.split(None, 1)
            if len(parts) < 2:
                return {'error': '缺少参数。使用: :receive [add|del|list|clear]'}

            params = shlex.split(parts[1])
        except ValueError:
            return {'error': '参数格式错误，带空格的参数请使用引号包裹'}

        if not params:
            return {'error': '缺少参数。使用: :receive [add|del|list|clear]'}

        operation = params[0]
        username = message_info.nickname

        if operation == 'add':
            if len(params) < 2:
                return {'error': '缺少命令内容。使用: :receive add "命令内容"'}

            command = params[1]
            if not command.startswith((':', '：', '/', '／')):
                return {'error': '命令必须以命令前缀(:/：或//／)开头，例如 ":say 谢谢"'}

            await ReceiveDao.create(username, command)
            return {'message': f'已添加收礼物命令: {command}'}

        elif operation == 'del':
            if len(params) < 2:
                return {'error': '缺少命令ID。使用: :receive del <id>'}

            try:
                command_id = int(params[1])
            except ValueError:
                return {'error': '命令ID必须是数字'}

            deleted = await ReceiveDao.delete_by_id(command_id)
            if deleted:
                return {'message': f'已删除命令 ID: {command_id}'}
            else:
                return {'error': f'未找到命令 ID: {command_id}'}

        elif operation == 'list':
            commands = await ReceiveDao.get_by_username(username)
            if not commands:
                return {'message': '您还没有设置任何收礼物命令'}

            message_lines = ['您的收礼物命令列表:']
            for cmd in commands:
                message_lines.append(f'  [{cmd.id}] {cmd.command}')

            return {'message': '\n'.join(message_lines)}

        elif operation == 'clear':
            count = await ReceiveDao.delete_all_by_username(username)
            if count > 0:
                return {'message': f'已清除 {count} 个收礼物命令'}
            else:
                return {'message': '您没有任何收礼物命令需要清除'}

        else:
            return {'error': f'未知操作: {operation}。使用: :receive [add|del|list|clear]'}

    async def user_gift_receive(self, username: str):
        """Called when a user sends a gift or heat contribution

        Args:
            username: Username of the user who sent the gift
        """
        try:
            commands = await ReceiveDao.get_by_username(username)
            if not commands:
                return

            from ushareiplay.core.message_queue import MessageQueue
            from ushareiplay.models.message_info import MessageInfo

            message_queue = MessageQueue.instance()
            for cmd in commands:
                message_info = MessageInfo(
                    content=cmd.command,
                    nickname=username
                )
                await message_queue.put_message(message_info)

        except Exception as e:
            if hasattr(self, 'handler') and self.handler and hasattr(self.handler, 'log_error'):
                self.handler.log_error(f"Error in receive user_gift_receive: {traceback.format_exc()}")
