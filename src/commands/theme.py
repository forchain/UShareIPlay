

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
        # Use singleton instances to ensure state synchronization
        self.theme_manager = ThemeManager.instance(self.handler)
        self.title_manager = TitleManager.instance(self.handler)

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

        # Verify theme was set correctly
        verify_result = self.theme_manager.verify_theme(theme)
        if 'error' in verify_result:
            return verify_result

        # Try to update room title with new theme
        ui_update_result = self._update_room_title_with_new_theme()

        response = {
            'theme': f'主题已更新为: {result["theme"]}'
        }
        
        # Add UI update result to response
        if ui_update_result:
            response.update(ui_update_result)

        return response

    def _update_room_title_with_new_theme(self):
        """Update room title with new theme
        Returns:
            dict: UI update result or None
        """
        try:
            # Get current or next title
            title_to_update = self.title_manager.get_title_to_update()
            
            if title_to_update:
                current_theme = self.theme_manager.get_current_theme()
                self.handler.logger.info(f'Updating room title with new theme: {current_theme}｜{title_to_update}')
                
                # Check if we can update now (shared cooldown)
                if self.theme_manager.can_update_now():
                    # Update title with new theme
                    result = self.title_manager.update_title_ui(title_to_update, current_theme)
                    # Always update cooldown time after attempt, regardless of success or failure
                    self.theme_manager.update_last_update_time()
                    
                    if 'error' not in result:
                        self.handler.logger.info('Room title updated successfully with new theme')
                        # Clear pending flag since UI update was successful
                        self.theme_manager.clear_pending_ui_update()
                        return {'ui_update': '房间标题已更新'}
                    else:
                        # Update failed - will retry in next cycle
                        self.handler.logger.info(f'Room title update failed, will retry in next cycle: {result["error"]}')
                        return {'ui_update': '房间标题更新失败，将在下个周期重试'}
                else:
                    remaining_minutes = self.theme_manager.get_remaining_cooldown_minutes()
                    self.handler.logger.info(f'Cannot update room title now, cooldown remaining: {remaining_minutes} minutes')
                    return {'ui_update': f'房间标题更新被冷却时间阻止，还需等待{remaining_minutes}分钟'}
            else:
                self.handler.logger.info('No current or next title to update with new theme')
                return {'ui_update': '没有标题可以更新'}
                
        except Exception as e:
            self.handler.log_error(f"Error updating room title with new theme: {str(e)}")
            return {'ui_update': f'房间标题更新出错: {str(e)}'}

    async def process(self, message_info, parameters):
        """Process theme command"""
        try:
            # If no parameters, return detailed status information
            if not parameters:
                current_theme = self.theme_manager.get_current_theme()
                current_title = self.title_manager.get_current_title()
                next_title = self.title_manager.get_next_title()
                remaining_minutes = self.theme_manager.get_remaining_cooldown_minutes()
                
                # Build status message
                status_parts = [f'当前主题: {current_theme}']
                
                if current_title:
                    status_parts.append(f'当前标题: {current_title}')
                else:
                    status_parts.append('当前标题: 未设置')
                
                if next_title:
                    status_parts.append(f'即将更新标题: {next_title}')
                    if remaining_minutes > 0:
                        status_parts.append(f'剩余更新时间: {remaining_minutes}分钟')
                    else:
                        status_parts.append('剩余更新时间: 可立即更新')
                else:
                    status_parts.append('即将更新标题: 无')
                
                return {'theme': '\n'.join(status_parts)}

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
        """Update method for background tasks - handle theme UI synchronization"""
        try:
            # Only process if there's a pending theme UI update
            if not self.theme_manager.has_pending_ui_update():
                return
            
            # Only attempt update if we can update now (cooldown has passed)
            if not self.theme_manager.can_update_now():
                return
            
            # Check if there's a title that needs theme synchronization
            title_to_update = self.title_manager.get_title_to_update()
            if not title_to_update:
                return  # No title to update with theme
            
            current_theme = self.theme_manager.get_current_theme()
            self.handler.logger.info(f'Processing pending theme sync: theme="{current_theme}", title="{title_to_update}"')
            
            # Attempt to update title with current theme
            result = self.title_manager.update_title_ui(title_to_update, current_theme)
            
            # Always update cooldown time after attempt
            self.theme_manager.update_last_update_time()
            
            if 'error' not in result:
                self.handler.logger.info(f'Theme synchronized with UI successfully: {current_theme}')
                # Clear the pending flag since UI update was successful
                self.theme_manager.clear_pending_ui_update()
            else:
                self.handler.logger.info(f'Theme sync failed, will retry later: {result["error"]}')
                # Keep pending flag set for retry
                
        except Exception as e:
            self.handler.log_error(f"Error in theme update: {str(e)}")
