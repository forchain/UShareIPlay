from ..core.base_command import BaseCommand

def create_command(controller):
    mic_command = MicCommand(controller)
    controller.mic_command = mic_command  # Store instance in controller
    return mic_command

command = None

class MicCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = controller.soul_handler

    def toggle_mic(self, target_state=None):
        """Toggle or set microphone state
        Args:
            target_state: Optional bool, True for on, False for off
        Returns:
            dict: Result with success or error
        """
        try:
            toggle_mic_button = self.handler.wait_for_element_clickable_plus('toggle_mic')

            if not toggle_mic_button:
                return {'error': 'Microphone button not found'}
            
            desc = self.handler.try_get_attribute(toggle_mic_button, 'content-desc')
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
            else:
                return {'error': f'Microphone is already {"on" if target_state else "off"}'}

        except Exception as e:
            self.handler.log_error(f"Error in mic command: {str(e)}")
            return {'error': str(e)}

    async def process(self, message_info, parameters):
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