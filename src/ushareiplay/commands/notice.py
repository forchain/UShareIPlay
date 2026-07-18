import traceback
from ushareiplay.core.base_command import BaseCommand

class NoticeCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = 'Failed to process notice command: {error}'

    def change_notice(self, notice: str):
        """Change room notice with cooldown check using NoticeManager"""
        # 使用NoticeManager的冷却时间管理
        from ushareiplay.managers.notice_manager import NoticeManager
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

    async def do_process(self, message_info, parameters):
        """Process notice command"""
        # Get new notice from parameters
        if not parameters:
            return {'error': 'Missing notice parameter'}

        new_notice = ' '.join(parameters)
        return self.change_notice(new_notice)

    def update(self):
        """Check and update notice periodically using NoticeManager"""
        try:
            # 使用NoticeManager处理待设置的notice
            from ushareiplay.managers.notice_manager import NoticeManager
            notice_manager = NoticeManager.instance()
            
            # 调用NoticeManager的update方法处理待设置的notice
            result = notice_manager.update()
            
            # 如果notice处理完成，发送消息通知
            if result and 'success' in result:
                # Extract notice content from success message
                success_message = result.get('success', '')
                notice_content = str(success_message).replace('Notice restored to: ', '')
                
                self.handler.logger.info(f'Notice update completed: {notice_content}')
                self.handler.send_message(f"Notice updated to: {notice_content}")

        except Exception:
            self.handler.log_error(f"Error in notice update: {traceback.format_exc()}")
