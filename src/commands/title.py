import traceback
import shlex

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
        # Use singleton instances to ensure state synchronization
        self.theme_manager = ThemeManager.instance()
        self.title_manager = TitleManager.instance()

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
        """Process title command
        
        Args:
            message_info: Message information
            parameters: List of parameters
                - 1 parameter: title only (e.g., :title "Estas Tonne" or :title 疗愈)
                - 2 parameters: title and theme (e.g., :title "Estas Tonne" "享乐" or :title 疗愈 助眠)
        
        Returns:
            dict: Result with title/theme info or error
        """
        try:
            # Get parameters
            if not parameters:
                return {'error': 'Missing title parameter'}

            # Parse parameters using shlex to handle quoted strings
            try:
                params = shlex.split(' '.join(parameters))
            except ValueError as e:
                self.handler.log_error(f"Error parsing parameters: {str(e)}")
                return {'error': 'Invalid parameter format. Use quotes for titles with spaces.'}
            
            if not params:
                return {'error': 'Missing title parameter'}
            
            # Extract title and optional theme
            new_title = params[0]
            new_theme = params[1] if len(params) >= 2 else None
            
            # If theme is provided, update theme first
            if new_theme:
                # Validate and set theme
                theme_result = self.theme_manager.set_theme(new_theme)
                if 'error' in theme_result:
                    return theme_result
                
                self.handler.logger.info(f"Theme will be updated to: {new_theme}")
            
            # Update title
            title_result = self.change_title(new_title)
            
            # Combine results
            if new_theme:
                # If theme was updated, include it in response
                if 'error' not in title_result:
                    response_parts = [f"主题: {new_theme}", title_result.get('title', '')]
                    return {'title': '\n'.join(response_parts)}
                else:
                    return title_result
            else:
                return title_result
                
        except Exception as e:
            self.handler.log_error(f"Error processing title command: {str(e)}")
            return {'error': f'Failed to process title command: {str(e)}'}

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

        except Exception:
            self.handler.log_error(f"Error in title update: {traceback.format_exc()}")
