import traceback
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
            parameters[0]: 操作类型（0=删除, 1=添加, 2=修改公开性）
            parameters[1]: 关键字（支持|分隔同义词）
            
            添加时：
            parameters[2]: 命令字符串
            parameters[3]: (可选) 公开性（1=公开，0=私有，默认1）
            
            修改公开性时：
            parameters[2]: (可选) 公开性（1=公开，0=私有，省略=切换）
        """
        try:
            self.handler.logger.info(f"Keyword command received: parameters={parameters}")
            if not parameters:
                return {'error': '缺少参数'}
            
            operation = parameters[0]
            
            if operation == '0':
                # 删除关键字
                if len(parameters) < 2:
                    return {'error': '缺少关键字参数'}
                keyword = parameters[1]
                return await self.keyword_manager.delete_keyword(
                    message_info.nickname, 
                    keyword
                )
                
            elif operation == '1':
                # 添加关键字
                if len(parameters) < 3:
                    return {'error': '缺少参数：关键字或命令'}
                keywords = parameters[1]
                command = parameters[2]
                is_public = True if len(parameters) < 4 else (parameters[3] == '1')
                
                return await self.keyword_manager.add_keyword(
                    message_info.nickname, 
                    keywords, 
                    command, 
                    is_public
                )
                
            elif operation == '2':
                # 修改公开性
                if len(parameters) < 2:
                    return {'error': '缺少关键字参数'}
                keyword = parameters[1]
                
                # 解析公开性参数
                if len(parameters) < 3:
                    # 省略参数，切换状态
                    is_public = None
                else:
                    # 指定参数
                    is_public = (parameters[2] == '1')
                
                return await self.keyword_manager.update_keyword_publicity(
                    message_info.nickname,
                    keyword,
                    is_public
                )
            else:
                return {'error': f'未知操作: {operation}'}
                
        except Exception:
            self.handler.log_error(f"Error processing keyword command: {traceback.format_exc()}")
            return {'error': '处理失败'}
