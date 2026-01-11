import traceback
from ..core.base_command import BaseCommand


def create_command(controller):
    say_command = SayCommand(controller)
    controller.say_command = say_command
    return say_command


command = None


class SayCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    async def process(self, message_info, parameters):
        """Process say command
        
        Args:
            message_info: MessageInfo object
            parameters: List of parameters (message content)
            
        Returns:
            dict: Result with success message or error
        """
        try:
            if not parameters:
                return {'error': '缺少消息内容。使用: :say <消息内容>'}
            
            # 将所有参数组合成消息
            message = ' '.join(parameters)
            
            if not message.strip():
                return {'error': '消息内容不能为空'}
            
            # 发送消息
            # self.handler.send_message(message)
            self.handler.logger.info(f"Say command executed by {message_info.nickname}: {message}")
            
            return {'message': f'{message}'}
        
        except Exception as e:
            self.handler.log_error(f"Error processing say command: {traceback.format_exc()}")
            return {'error': '发送消息失败'}
