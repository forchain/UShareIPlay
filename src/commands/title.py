import time
import traceback
from datetime import datetime

from ..core.base_command import BaseCommand
from ..managers.title_manager import TitleManager
from ..managers.theme_manager import ThemeManager


def create_command(controller):
    title_command = TitleCommand(controller)
    controller.title_command = title_command
    return title_command


command = None


class TitleCommand(BaseCommand):

    def __init__(self, controller):
        super().__init__(controller)

        self.handler = controller.soul_handler
        # Create or get shared theme_manager from controller
        if not hasattr(controller, 'shared_theme_manager'):
            controller.shared_theme_manager = ThemeManager(self.handler)
        self.theme_manager = controller.shared_theme_manager
        self.title_manager = TitleManager(self.handler, self.theme_manager)

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

        # Use title manager to set next title
        return self.title_manager.set_next_title(title)

    def get_current_title(self):
        """Get current title
        Returns:
            str: Current title or None if not set
        """
        return self.title_manager.get_current_title()

    def get_next_title(self):
        """Get next title
        Returns:
            str: Next title or None if not set
        """
        return self.title_manager.get_next_title()

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
        """Check and update title periodically with simple retry logic"""
        # super().update()

        try:
            if not self.title_manager.get_next_title():
                return

            # Only attempt update if we can update now (cooldown has passed)
            if not self.title_manager.can_update_now():
                return

            title_to_update = self.title_manager.get_next_title()
            current_theme = self.theme_manager.get_current_theme()
            
            self.handler.logger.info(f'Title update attempt: title="{title_to_update}", theme="{current_theme}"')
            
            # Attempt to update
            result = self.title_manager.update_title_ui(title_to_update, current_theme)
            
            # Always update cooldown time after attempt, regardless of success or failure
            if self.theme_manager:
                self.theme_manager.update_last_update_time()
            
            if 'error' not in result:
                # Success - update completed
                self.handler.logger.info(f'标题更新成功: {self.title_manager.get_current_title()}')
                self.handler.send_message(
                    f"标题已更新为: {self.title_manager.get_current_title()}"
                )
            else:
                # Failed - will retry after next cooldown period
                self.handler.logger.info(f'标题更新失败，将在下个周期重试: {result["error"]}')

        except Exception as e:
            self.handler.log_error(f"Error in title update: {traceback.format_exc()}")
