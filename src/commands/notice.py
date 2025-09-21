import traceback
from ..core.base_command import BaseCommand


def create_command(controller):
    notice_command = NoticeCommand(controller)
    controller.notice_command = notice_command
    return notice_command


command = None


class NoticeCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

        self.handler = self.soul_handler

    def change_notice(self, notice: str):
        """Change room notice with cooldown check using NoticeManager"""
        # 使用NoticeManager的冷却时间管理
        from ..managers.notice_manager import NoticeManager
        notice_manager = NoticeManager.instance()
        
        result = notice_manager.set_notice(notice)
        
        if 'success' in result:
            self.handler.logger.info(f'Notice updated to {notice}')
            return {'notice': f'{notice}'}
        elif 'cooldown' in result:
            remaining_minutes = result.get('remaining_minutes', 0)
            self.handler.logger.info(f'Notice will be updated to {notice} in {remaining_minutes} minutes')
            return {'notice': f'{notice}. Notice will update in {remaining_minutes} minutes'}
        else:
            # 错误情况
            error_msg = result.get('error', 'Unknown error')
            self.handler.logger.error(f'Failed to update notice: {error_msg}')
            return {'error': f'Failed to update notice: {error_msg}'}

    async def process(self, message_info, parameters):
        """Process notice command"""
        try:
            # Get new notice from parameters
            if not parameters:
                return {'error': 'Missing notice parameter'}

            new_notice = ' '.join(parameters)
            return self.change_notice(new_notice)
        except Exception as e:
            self.handler.log_error(f"Error processing notice command: {str(e)}")
            return {'error': f'Failed to process notice command: {str(e)}'}

    def update(self):
        """Check and update notice periodically using NoticeManager"""
        try:
            # 使用NoticeManager处理待设置的notice
            from ..managers.notice_manager import NoticeManager
            notice_manager = NoticeManager.instance()
            
            # 调用NoticeManager的update方法处理待设置的notice
            result = notice_manager.update()
            
            # 如果notice处理完成，发送消息通知
            if result and 'success' in result:
                notice_content = result.get('success', '').replace('Notice restored to: ', '')
                self.handler.logger.info(f'Notice update completed: {notice_content}')
                self.handler.send_message(f"Notice updated to: {notice_content}")

        except Exception:
            self.handler.log_error(f"Error in notice update: {traceback.format_exc()}")

