from ushareiplay.core.base_command import BaseCommand


class SayCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '发送消息失败'

    async def do_process(self, message_info, parameters):
        """Process say command

        Args:
            message_info: MessageInfo object
            parameters: List of parameters (message content)

        Returns:
            dict: Result with success message or error
        """
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
