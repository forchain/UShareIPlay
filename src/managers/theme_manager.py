import logging
from datetime import datetime

class ThemeManager:
    def __init__(self, handler):
        self.handler = handler
        self.logger = logging.getLogger('theme_manager')
        self.current_theme = "享乐"  # 默认主题
        self.last_update_time = None  # 共享的冷却时间
        self.cooldown_minutes = 10  # 10分钟冷却时间
        self.is_initialized = False  # 是否已初始化

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

    def can_update_now(self):
        """Check if can update now (not in cooldown)
        Returns:
            bool: True if can update, False if in cooldown
        """
        if not self.last_update_time:
            return True

        current_time = datetime.now()
        time_diff = current_time - self.last_update_time
        return time_diff.total_seconds() >= self.cooldown_minutes * 60

    def get_remaining_cooldown_minutes(self):
        """Get remaining cooldown minutes
        Returns:
            int: Remaining minutes, 0 if no cooldown
        """
        if not self.last_update_time:
            return 0

        current_time = datetime.now()
        time_diff = current_time - self.last_update_time
        remaining_seconds = self.cooldown_minutes * 60 - time_diff.total_seconds()
        return max(0, int(remaining_seconds / 60))

    def update_last_update_time(self):
        """Update last update time to current time"""
        self.last_update_time = datetime.now()
        self.logger.info(f'Updated last update time to {self.last_update_time}')

    def initialize_from_ui(self):
        """Initialize theme from UI (only for first time initialization)
        Returns:
            dict: Result with success or error
        """
        if self.is_initialized:
            self.logger.info("Theme already initialized, skipping UI initialization")
            return {'success': True, 'theme': self.current_theme, 'already_initialized': True}

        try:
            # Find room title element
            room_title_element = self.handler.try_find_element_plus('chat_room_title', log=False)
            if not room_title_element:
                self.logger.info("Room title element not found for initialization")
                return {'error': 'Room title element not found'}

            # Get room title text
            room_title_text = self.handler.get_element_text(room_title_element)
            if not room_title_text:
                self.logger.info("Room title text is empty for initialization")
                return {'error': 'Room title text is empty'}

            # Parse theme from room name
            # Expected format: "主题｜标题"
            if '｜' in room_title_text:
                parts = room_title_text.split('｜', 1)
                if len(parts) == 2:
                    theme_part = parts[0].strip()
                    self.current_theme = theme_part
                    self.is_initialized = True
                    self.logger.info(f'Initialized theme from UI: {theme_part}')
                    return {
                        'success': True,
                        'theme': theme_part,
                        'initialized': True
                    }

            # If no separator found, use default theme
            self.is_initialized = True
            self.logger.info(f'No theme separator found, using default: {self.current_theme}')
            return {
                'success': True,
                'theme': self.current_theme,
                'initialized': True
            }

        except Exception as e:
            self.logger.error(f"Error initializing theme from UI: {str(e)}")
            return {'error': f'Failed to initialize theme from UI: {str(e)}'}

    def verify_theme(self, expected_theme: str):
        """Verify if current theme matches expected theme
        Args:
            expected_theme: str, expected theme text
        Returns:
            dict: Result with success or error
        """
        if self.current_theme == expected_theme:
            self.logger.info(f'Theme verification passed: {expected_theme}')
            return {'success': True, 'theme': self.current_theme}
        else:
            self.logger.error(f'Theme verification failed: expected {expected_theme}, got {self.current_theme}')
            return {'error': f'Theme verification failed: expected {expected_theme}, got {self.current_theme}'}

    def reset_theme(self):
        """Reset theme to default
        Returns:
            dict: Result with success or error
        """
        return self.set_theme("享乐")


