import traceback
import shlex
from ..core.base_command import BaseCommand


def create_command(controller):
    keyword_command = KeywordCommand(controller)
    controller.keyword_command = keyword_command
    return keyword_command


command = None


class KeywordCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = controller.soul_handler
        
        # 初始化关键字管理器
        from ..managers.keyword_manager import KeywordManager
        self.keyword_manager = KeywordManager.instance()

    async def process(self, message_info, parameters):
        """Process keyword command
        
        Args:
            message_info: MessageInfo object containing original message content
            parameters: List of parameters (may be pre-split, use original content for proper parsing)
        
        Note: Uses original message content to properly parse quoted strings
        """
        try:
            # Get original message content from message_info to properly parse quoted strings
            # The content format is: "keyword 1 7 \":play 唯一的你;给你点首歌\""
            original_content = message_info.content
            
            self.handler.logger.info(f"Keyword command received: original_content={original_content}, parameters={parameters}")
            
            # Parse the full command using shlex to handle quoted strings properly
            # Extract command name and parameters
            try:
                # Split by space to get command and rest
                parts = original_content.split(None, 1)  # Split only on first space
                if len(parts) < 2:
                    return {'error': '缺少参数'}
                
                # Parse parameters using shlex
                params = shlex.split(parts[1])
            except ValueError as e:
                self.handler.log_error(f"Error parsing parameters: {str(e)}")
                return {'error': '参数格式错误，带空格的参数请使用引号包裹'}
            
            if not params:
                return {'error': '缺少参数'}
            
            operation = params[0]
            
            if operation == '0':
                # 删除关键字
                if len(params) < 2:
                    return {'error': '缺少关键字参数'}
                keyword = params[1]
                return await self.keyword_manager.delete_keyword(
                    message_info.nickname, 
                    keyword
                )
                
            elif operation == '1':
                # 添加关键字
                if len(params) < 3:
                    return {'error': '缺少参数：关键字或命令'}
                keywords = params[1]
                command = params[2]
                is_public = True if len(params) < 4 else (params[3] == '1')
                
                return await self.keyword_manager.add_keyword(
                    message_info.nickname, 
                    keywords, 
                    command, 
                    is_public
                )
                
            elif operation == '2':
                # 修改公开性
                if len(params) < 2:
                    return {'error': '缺少关键字参数'}
                keyword = params[1]
                
                # 解析公开性参数
                if len(params) < 3:
                    # 省略参数，切换状态
                    is_public = None
                else:
                    # 指定参数
                    is_public = (params[2] == '1')
                
                return await self.keyword_manager.update_keyword_publicity(
                    message_info.nickname,
                    keyword,
                    is_public
                )
                
            elif operation == '3':
                # 立即执行关键字
                if len(params) < 2:
                    return {'error': '缺少关键字参数'}
                keyword = params[1]
                
                # 查找关键字
                keyword_record = await self.keyword_manager.find_keyword(
                    keyword, 
                    message_info.nickname
                )
                
                if not keyword_record:
                    return {'error': f'关键字 "{keyword}" 不存在或无权限执行'}
                
                # 立即执行关键字
                await self.keyword_manager.execute_keyword(
                    keyword_record,
                    message_info.nickname
                )
                
                return {'message': f'已执行关键字 "{keyword}"'}
                
            else:
                return {'error': f'未知操作: {operation}'}
                
        except Exception:
            self.handler.log_error(f"Error processing keyword command: {traceback.format_exc()}")
            return {'error': '处理失败'}
