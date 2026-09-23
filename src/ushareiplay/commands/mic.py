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
            just_seated = False
            if target_state is not False and not self.handler.is_on_seat():
                # 开麦前先确认已在麦位：不在麦位时界面只提供抢麦入口，
                # 直接点击开麦按钮会失败或抛错。
                if not self.handler.ensure_on_seat():
                    return {'error': 'Failed to grab mic, not seated yet'}
                just_seated = True
                # 抢麦前必然未开麦，因此裸 :mic 这一刻等同于开麦，
                # 而不是把随座位自动打开的麦克风再关掉。
                target_state = True

            toggle_mic_button = self.handler.element_finder.wait_for_element_clickable('toggle_mic')

            if not toggle_mic_button:
                return {'error': 'Microphone button not found'}

            desc = self.handler.element_finder.try_get_attribute(toggle_mic_button, 'content-desc')
            if not desc:
                self.handler.logger.error('failed to get mic status')
                return {'error': 'Failed to get mic status'}

            is_mic_on = desc == "闭麦按钮"  # If we see "闭麦按钮", mic is currently on

            if target_state is None:
                # Toggle current state
                toggle_mic_button.click()
                new_state = "1" if not is_mic_on else "0"  # If mic was off, now it's on (1)
                self.handler.logger.info(f"Toggled mic to {new_state}")
                return {'state': new_state}

            # Only click if current state doesn't match target state
            if is_mic_on != target_state:
                toggle_mic_button.click()
                self.handler.logger.info(f"Set mic to {1 if target_state else 0}")
                return {'state': "1" if target_state else "0"}
            elif just_seated:
                # 抢麦就座后麦克风已随座位自动打开，目标状态已达成，不算“已开麦”报错
                self.handler.logger.info("Mic already on after seating")
                return {'state': "1"}
            else:
                return {'error': f'Microphone is already {"on" if target_state else "off"}'}

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
