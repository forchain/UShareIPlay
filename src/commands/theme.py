import time
import traceback
from datetime import datetime

from ..core.base_command import BaseCommand
from ..managers.theme_manager import ThemeManager
from ..managers.title_manager import TitleManager


def create_command(controller):
    theme_command = ThemeCommand(controller)
    controller.theme_command = theme_command
    return theme_command


command = None


class ThemeCommand(BaseCommand):

    def __init__(self, controller):
        super().__init__(controller)

        self.handler = controller.soul_handler
        self.theme_manager = ThemeManager(self.handler)
        self.title_manager = TitleManager(self.handler, self.theme_manager)

    def change_theme(self, theme: str):
        """Change room theme
        Args:
            theme: str, new theme text (max 2 characters)
        Returns:
            dict: Result with theme info or error
        """
        # Switch to Soul app first
        if not self.handler.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        self.handler.logger.info("Switched to Soul app")

        # Update theme using theme manager
        result = self.theme_manager.set_theme(theme)
        if 'error' in result:
            return result

        # Try to update room title with new theme
        self._update_room_title_with_new_theme()

        return {
            'theme': f'主题已更新为: {result["theme"]}'
        }

    def _update_room_title_with_new_theme(self):
        """Update room title with new theme"""
        try:
            # Get current or next title
            title_to_update = self.title_manager.get_title_to_update()
            
            if title_to_update:
                current_theme = self.theme_manager.get_current_theme()
                self.handler.logger.info(f'Updating room title with new theme: {current_theme}｜{title_to_update}')
                
                # Force update title with new theme (bypass cooldown for theme changes)
                result = self.title_manager.force_update_title(title_to_update, current_theme)
                if 'error' not in result:
                    self.handler.logger.info(f'Room title updated successfully with new theme')
                    
                    # Sync theme manager with the actual UI state after update
                    sync_result = self.theme_manager.sync_theme_from_ui()
                    if 'error' not in sync_result:
                        self.handler.logger.info(f'Synced theme manager after UI update: {sync_result.get("theme", "unknown")}')
                else:
                    self.handler.log_warning(f'Failed to update room title with new theme: {result["error"]}')
            else:
                self.handler.logger.info('No current or next title to update with new theme')
                
        except Exception as e:
            self.handler.log_error(f"Error updating room title with new theme: {str(e)}")

    async def process(self, message_info, parameters):
        """Process theme command"""
        try:
            # Get new theme from parameters
            if not parameters:
                return {'error': '缺少主题参数'}

            new_theme = ' '.join(parameters)
            return self.change_theme(new_theme)
        except Exception as e:
            self.handler.log_error(f"Error processing theme command: {str(e)}")
            return {'error': f'处理主题命令失败: {str(e)}'}

    def get_current_theme(self):
        """Get current theme
        Returns:
            str: Current theme
        """
        return self.theme_manager.get_current_theme()

    def update(self):
        """Update method for background tasks"""
        # 主题命令不需要定期更新
        pass
