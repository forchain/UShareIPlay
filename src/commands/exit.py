import traceback
import shlex
from ..core.base_command import BaseCommand
from ..dal.exit_dao import ExitDao


def create_command(controller):
    exit_command = ExitCommand(controller)
    controller.exit_command = exit_command
    return exit_command


command = None


class ExitCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    async def process(self, message_info, parameters):
        """Process exit command
        
        Args:
            message_info: MessageInfo object
            parameters: List of parameters
            
        Returns:
            dict: Result with success message or error
        """
        try:
            # Parse parameters using shlex to handle quoted strings
            try:
                # Get original message content to properly parse quoted strings
                original_content = message_info.content
                # Remove the command prefix ":exit"
                parts = original_content.split(None, 1)
                if len(parts) < 2:
                    return {'error': '缺少参数。使用: :exit [add|del|list|clear]'}
                
                # Parse parameters
                params = shlex.split(parts[1])
            except ValueError as e:
                return {'error': '参数格式错误，带空格的参数请使用引号包裹'}
            
            if not params:
                return {'error': '缺少参数。使用: :exit [add|del|list|clear]'}
            
            operation = params[0]
            username = message_info.nickname
            
            # Handle different operations
            if operation == 'add':
                if len(params) < 2:
                    return {'error': '缺少命令内容。使用: :exit add "命令内容"'}
                
                command = params[1]
                
                # Validate command format (should start with :)
                if not command.startswith(':'):
                    return {'error': '命令必须以冒号(:)开头，例如 ":play 歌曲名"'}
                
                # Add to database using DAO
                await ExitDao.create(username, command)
                
                return {'message': f'已添加离开命令: {command}'}
            
            elif operation == 'del':
                if len(params) < 2:
                    return {'error': '缺少命令ID。使用: :exit del <id>'}
                
                try:
                    command_id = int(params[1])
                except ValueError:
                    return {'error': '命令ID必须是数字'}
                
                # Delete from database using DAO
                deleted = await ExitDao.delete_by_id(command_id)
                
                if deleted:
                    return {'message': f'已删除命令 ID: {command_id}'}
                else:
                    return {'error': f'未找到命令 ID: {command_id}'}
            
            elif operation == 'list':
                # Get all commands for this user using DAO
                commands = await ExitDao.get_by_username(username)
                
                if not commands:
                    return {'message': '您还没有设置任何离开命令'}
                
                # Format the list
                message_lines = ['您的离开命令列表:']
                for cmd in commands:
                    message_lines.append(f'  [{cmd.id}] {cmd.command}')
                
                return {'message': '\n'.join(message_lines)}
            
            elif operation == 'clear':
                # Delete all commands for this user using DAO
                count = await ExitDao.delete_all_by_username(username)
                
                if count > 0:
                    return {'message': f'已清除 {count} 个离开命令'}
                else:
                    return {'message': '您没有任何离开命令需要清除'}
            
            else:
                return {'error': f'未知操作: {operation}。使用: :exit [add|del|list|clear]'}
        
        except Exception as e:
            self.handler.log_error(f"Error processing exit command: {traceback.format_exc()}")
            return {'error': '处理离开命令时出错'}

    async def user_leave(self, username: str):
        """Called when a user leaves the party
        
        Args:
            username: Username of the user who left
        """
        try:
            # Get all exit commands for this user using DAO
            commands = await ExitDao.get_by_username(username)
            
            if not commands:
                return
            
            self.handler.logger.info(f"User {username} left, executing {len(commands)} exit command(s)")
            
            # Execute each command
            from ..core.message_queue import MessageQueue
            from ..models.message_info import MessageInfo
            
            message_queue = MessageQueue.instance()
            
            for cmd in commands:
                # Create MessageInfo object
                message_info = MessageInfo(
                    content=cmd.command,
                    nickname=username
                )
                
                # Put message in queue for processing
                await message_queue.put_message(message_info)
                self.handler.logger.info(f"Queued exit command [{cmd.id}] for {username}: {cmd.command}")
        
        except Exception as e:
            self.handler.log_error(f"Error in exit user_leave: {traceback.format_exc()}")
