from ushareiplay.core.base_command import BaseCommand


class MicCommand(BaseCommand):
    handler_attr = 'soul_handler'

    def toggle_mic(self, target_state=None):
        """Toggle or set microphone state
        Args:
            target_state: Optional bool, True for on, False for off
        Returns:
            dict: Result with success or error
        """
        try:
            if target_state is None:
                if not self.handler.is_on_seat():
                    # 抢麦会随座位自动开麦，因此不在麦位时裸 :mic 等同于开麦，
                    # 而不是刚就座就把麦克风关掉。
                    target_state = True
                else:
                    current = self.mic_manager.state()
                    if current is None:
                        self.handler.logger.error('failed to get mic status')
                        return {'error': 'Failed to get mic status'}
                    target_state = not current

            # 麦克风状态读取、麦位前置检查与点击都归 MicManager；
            # report_noop 让「已开麦/已闭麦」仍然作为提示返回给聊天。
            return self.mic_manager.set_active(target_state, report_noop=True)

        except Exception as e:
            self.handler.log_error(f"Error in mic command: {str(e)}")
            return {'error': str(e)}

    async def do_process(self, message_info, parameters):
        """Process mic command
        Args:
            message_info: MessageInfo object
            parameters: List of parameters
        Returns:
            dict: Result with success or error
        """
        if not parameters:
            return self.toggle_mic()

        action = parameters[0]
        if action not in ['0', '1']:
            return {'error': 'Invalid parameter. Usage: :mic 0/1'}

        return self.toggle_mic(action == '1')  # Convert to bool: True for on, False for off
