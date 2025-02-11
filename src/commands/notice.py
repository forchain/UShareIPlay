import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time


def create_command(controller):
    notice_command = NoticeCommand(controller)
    controller.notice_command = notice_command
    return notice_command


command = None


class NoticeCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

        self.handler = self.soul_handler
        self.last_update_time = None
        self.current_notice = None
        self.next_notice = None
        self.cooldown_minutes = 15  # Same cooldown as topic

    def change_notice(self, notice: str):
        """Change room notice with cooldown check"""
        current_time = datetime.now()

        # Update notice
        self.next_notice = notice

        if not self.last_update_time:
            self.handler.logger.info(f'Notice will be updated to {notice} soon')
            return {
                'notice': f'{notice}. Notice will update soon'
            }

        time_diff = current_time - self.last_update_time
        remaining_minutes = self.cooldown_minutes - (time_diff.total_seconds() / 60)
        if remaining_minutes < 0:
            self.handler.logger.info(f'Notice is updating to {notice} soon')
            return {
                'notice': f'{notice}. Notice will update soon'
            }

        self.handler.logger.info(f'Notice will be updated to {notice} in {remaining_minutes} minutes')
        return {
            'notice': f'{notice}. Notice will update in {int(remaining_minutes)} minutes'
        }

    def process(self, message_info, parameters):
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
        """Check and update notice periodically"""

        try:
            if not self.next_notice:
                return

            on_time = False
            current_time = datetime.now()
            if self.last_update_time:
                time_diff = current_time - self.last_update_time
                if time_diff.total_seconds() >= self.cooldown_minutes * 60:
                    on_time = True
            else:
                on_time = True

            if not on_time:
                return

            # Check if cooldown period has passed
            result = self._update_notice(self.next_notice)
            if not 'error' in result:
                self.handler.logger.info(f'Notice is updated to {self.current_notice}')
                self.handler.send_message(
                    f"Updating notice to: {self.current_notice}"
                )

        except Exception as e:
            self.handler.log_error(f"Error in notice update: {traceback.format_exc()}")

    def _update_notice(self, notice):
        """Update room notice
        Args:
            notice: New notice text
        Returns:
            dict: Result with error or success
        """
        try:
            # Click little assistant
            assistant = self.handler.wait_for_element_clickable_plus('little_assistant')
            if not assistant:
                return {'error': 'Failed to find little assistant'}
            assistant.click()

            # Click edit notice entry
            edit_entry = self.handler.wait_for_element_clickable_plus('edit_notice_entry')
            if not edit_entry:
                return {'error': 'Failed to find edit notice entry'}
            edit_entry.click()

            # Click customize notice button
            customize = self.handler.wait_for_element_clickable_plus('customize_notice_button')
            if not customize:
                return {'error': 'Failed to find customize notice button'}
            customize.click()

            # Input new notice
            notice_input = self.handler.wait_for_element_clickable_plus('edit_notice_input')
            if not notice_input:
                return {'error': 'Failed to find notice input'}
            notice_input.clear()
            notice_input.send_keys(notice)

            # Click confirm
            confirm = self.handler.wait_for_element_clickable_plus('edit_notice_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            self.last_update_time = datetime.now()
            self.current_notice = self.next_notice
            self.next_notice = None

            edit_entry = self.handler.wait_for_element_clickable_plus('edit_notice_entry', timeout=1)
            if edit_entry:
                self.handler.press_back()
                self.handler.logger.info(f'Hide notice setting dialog')

            return {'success': True}

        except Exception as e:
            self.handler.log_error(f"Error in notice update: {traceback.format_exc()}")
            return {'error': f'Failed to update notice to {notice}'}
