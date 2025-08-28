import traceback
from datetime import datetime

from ..core.base_command import BaseCommand


def create_command(controller):
    title_command = TitleCommand(controller)
    controller.title_command = title_command
    return title_command


command = None


class TitleCommand(BaseCommand):

    def __init__(self, controller):
        super().__init__(controller)

        self.last_update_time = None
        self.current_title = None
        self.next_title = None
        self.cooldown_minutes = 10
        self.handler = controller.soul_handler

    def change_title(self, title: str):
        """Change room title with cooldown check
        Args:
            title: str, new title text
        Returns:
            dict: Result with title info or error
        """
        # Switch to Soul app first
        if not self.handler.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        self.handler.logger.info("Switched to Soul app")

        new_title = title.split('|')[0].split('(')[0].strip()[:12]
        current_time = datetime.now()

        # Update title
        self.next_title = new_title

        if not self.last_update_time:
            self.handler.logger.info(f'Title will be updated to {new_title} soon')
            return {
                'title': f'{new_title}. Title will update soon'
            }

        time_diff = current_time - self.last_update_time
        remaining_minutes = self.cooldown_minutes - (time_diff.total_seconds() / 60)
        if remaining_minutes < 0:
            self.handler.logger.info(f'Title will be updated to {new_title} soon')
            return {
                'title': f'{new_title}. Title will update soon'
            }

        self.handler.logger.info(f'Title will be updated to {new_title} in {remaining_minutes} minutes')
        return {
            'title': f'{new_title}. Title will update in {int(remaining_minutes)} minutes'
        }

    async def process(self, message_info, parameters):
        """Process title command"""
        try:
            # Get new title from parameters
            if not parameters:
                return {'error': 'Missing title parameter'}

            new_title = ' '.join(parameters)
            return self.change_title(new_title)
        except Exception as e:
            self.handler.log_error(f"Error processing title command: {str(e)}")
            return {'error': f'Failed to process title command, {new_title}'}

    def update(self):
        """Check and update title periodically"""
        # super().update()

        try:
            if not self.next_title:
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
            result = self._update_title(self.next_title)
            if not 'error' in result:
                self.handler.logger.info(f'Title is updated to {self.current_title}')
                self.handler.send_message(
                    f"Updating title to {self.current_title}"
                )


        except Exception as e:
            self.handler.log_error(f"Error in title update: {traceback.format_exc()}")

    def _update_title(self, title):
        """Update room title
        Args:
            title: New title text
        Returns:
            dict: Result with error or success
        """
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
            if not self.handler.click_element_at(edit_entry, y_ratio=0.25):
                return {'error': 'Failed to click edit entry'}

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

            current_time = datetime.now()
            self.last_update_time = current_time
            self.handler.logger.info(f'updated last title update time to {current_time}')

            key, element = self.handler.wait_for_any_element_plus(['title_edit_entry', 'title_edit_confirm'])
            if key == 'title_edit_entry':
                self.current_title = self.next_title
                self.next_title = None
                self.handler.logger.info(f'updated last title edit time to {current_time}')
            elif key == 'title_edit_confirm':
                go_back = self.handler.wait_for_element_plus('go_back')
                if go_back:
                    go_back.click()
                    self.handler.logger.warning('Update title too frequently, go back to chat room info screen')

            self.handler.press_back()
            self.handler.logger.info('Hide edit title dialog')

            return {'success': True}

        except Exception as e:
            self.handler.log_error(f"Error in title update: {traceback.format_exc()}")
            return {'error': f'Failed to update title: {title}'}
