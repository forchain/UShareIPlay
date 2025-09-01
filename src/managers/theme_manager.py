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
