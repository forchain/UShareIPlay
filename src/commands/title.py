import traceback
from ..core.base_command import BaseCommand
from datetime import datetime
import time

def create_command(controller):
    title_command = TitleCommand(controller)
    controller.title_command = title_command
    return title_command

command = None

class TitleCommand(BaseCommand):
    prefix = "title"
    response_template = "Changing title to {title}"
    cooldown_minutes = 17  # Cooldown period in minutes

    def __init__(self, controller):
        super().__init__(controller)
        self.last_update_time = None
        self.next_title = None
        self.handler = controller.soul_handler

    def process(self, message_info, parameters):
        """Process change title command"""
        try:
            if not parameters:
                return {'error': 'Missing title parameter'}

            new_title = ' '.join(parameters)[:12]  # Limit title to 12 characters
            self.next_title = new_title
            current_time = datetime.now()

            if not self.last_update_time:
                self.last_update_time = current_time
                return {
                    'title': f'Title will be updated to "{new_title}" soon.'
                }

            time_diff = current_time - self.last_update_time
            remaining_minutes = self.cooldown_minutes - (time_diff.total_seconds() / 60)

            if remaining_minutes > 0:
                return {
                    'title': f'Title will update in {int(remaining_minutes)} minutes.'
                }

            # If cooldown period has passed, update the title
            self.update_title(new_title)
            self.last_update_time = current_time
            return {
                'title': f'Title updated to "{new_title}".'
            }

        except Exception as e:
            self.handler.log_error(f"Error processing change title command: {str(e)}")
            return {'error': f'Failed to process change title command, {new_title}'}

    def update_title(self, title):
        """Update the room title"""
        try:
            # Click room title
            room_title = self.handler.wait_for_element_clickable_plus('chat_room_title')
            if not room_title:
                return {'error': 'Failed to find room title'}
            room_title.click()

            # Click edit entry
            edit_entry = self.handler.wait_for_element_clickable_plus('title_edit_entry')
            if not edit_entry:
                return {'error': 'Failed to find edit title entry'}
            edit_entry.click()

            # Input new title
            title_input = self.handler.wait_for_element_clickable_plus('title_edit_input')
            if not title_input:
                return {'error': 'Failed to find title input'}
            title_input.clear()
            title_input.send_keys("享乐｜" + title)

            # Click confirm
            confirm = self.handler.wait_for_element_clickable_plus('title_edit_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            return {'success': True}

        except Exception as e:
            self.handler.log_error(f"Error in title update: {traceback.format_exc()}")
            return {'error': f'Failed to update title: {title}'}

    def update(self):
        """Check and update title periodically"""
        try:
            if not self.next_title:
                return

            current_time = datetime.now()
            if self.last_update_time:
                time_diff = current_time - self.last_update_time
                if time_diff.total_seconds() >= self.cooldown_minutes * 60:
                    self.update_title(self.next_title)
                    self.last_update_time = current_time
                    self.next_title = None

        except Exception as e:
            self.handler.log_error(f"Error in title update: {traceback.format_exc()}") 