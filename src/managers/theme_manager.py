import logging
from datetime import datetime

class ThemeManager:
    def __init__(self, handler):
        self.handler = handler
        self.logger = logging.getLogger('theme_manager')
        self.current_theme = "享乐"  # 默认主题

    def get_current_theme(self):
        """Get current theme
        Returns:
            str: Current theme
        """
        return self.current_theme

    def set_theme(self, theme: str):
        """Set new theme
        Args:
            theme: str, new theme text (max 2 characters)
        Returns:
            dict: Result with success or error
        """
        # Validate theme length
        if len(theme) > 2:
            return {'error': '主题最多两个字符'}

        new_theme = theme.strip()
        if not new_theme:
            return {'error': '主题不能为空'}

        # Update theme
        old_theme = self.current_theme
        self.current_theme = new_theme
        self.logger.info(f'Theme updated from {old_theme} to {new_theme}')

        return {
            'success': True,
            'theme': new_theme,
            'old_theme': old_theme
        }

    def reset_theme(self):
        """Reset theme to default
        Returns:
            dict: Result with success or error
        """
        return self.set_theme("享乐")

    def sync_theme_from_ui(self):
        """Sync theme from UI to manager state
        Returns:
            dict: Result with success or error
        """
        try:
            # Find room title element
            room_title_element = self.handler.try_find_element_plus('chat_room_title', log=False)
            if not room_title_element:
                self.logger.info("Room title element not found for theme sync")
                return {'error': 'Room title element not found'}

            # Get room title text
            room_title_text = self.handler.get_element_text(room_title_element)
            if not room_title_text:
                self.logger.info("Room title text is empty for theme sync")
                return {'error': 'Room title text is empty'}

            # Parse theme from room name
            # Expected format: "主题｜标题"
            if '｜' in room_title_text:
                parts = room_title_text.split('｜', 1)
                if len(parts) == 2:
                    theme_part = parts[0].strip()
                    
                    # Update theme if different
                    if theme_part != self.current_theme:
                        old_theme = self.current_theme
                        self.current_theme = theme_part
                        self.logger.info(f'Synced theme from UI: {old_theme} -> {theme_part}')
                        return {
                            'success': True,
                            'theme': theme_part,
                            'old_theme': old_theme
                        }
                    else:
                        self.logger.info(f'Theme already in sync: {theme_part}')
                        return {
                            'success': True,
                            'theme': theme_part,
                            'synced': True
                        }
            
            # If no separator found, use default theme
            if self.current_theme != "享乐":
                old_theme = self.current_theme
                self.current_theme = "享乐"
                self.logger.info(f'No theme separator found, reset to default: {old_theme} -> 享乐')
                return {
                    'success': True,
                    'theme': "享乐",
                    'old_theme': old_theme
                }
            
            return {
                'success': True,
                'theme': self.current_theme,
                'synced': True
            }
            
        except Exception as e:
            self.logger.error(f"Error syncing theme from UI: {str(e)}")
            return {'error': f'Failed to sync theme from UI: {str(e)}'}
