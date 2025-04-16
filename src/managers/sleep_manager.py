import traceback
from ..core.singleton import Singleton
from ..managers.theme_manager import ThemeManager
from ..dal import UserDAO

class SleepManager(Singleton):
    def _init(self, handler=None):
        self.handler = handler
        self.is_sleep_mode = False
        self.theme_manager = ThemeManager(handler)
        self.required_level = 8

    async def set_sleep_mode(self, username: str, enable: bool) -> dict:
        """Set sleep mode
        Args:
            username: str, username of the user trying to set sleep mode
            enable: bool, True to enable sleep mode, False to disable
        Returns:
            dict: Result with status info
        """
        try:
            # Check user level
            user = await UserDAO.get_by_username(username)
            if not user or user.level < self.required_level:
                return {'error': f'Only users with level >= {self.required_level} can manage sleep mode'}

            self.is_sleep_mode = enable
            if enable:
                # Set theme mode to '助眠'
                self.theme_manager.change_theme(mode='助眠')
                return {'status': 'Sleep mode enabled'}
            else:
                return {'status': 'Sleep mode disabled'}
        except Exception as e:
            self.handler.log_error(f"Error setting sleep mode: {traceback.format_exc()}")
            return {'error': f'Failed to set sleep mode: {str(e)}'}

    def get_sleep_mode(self) -> dict:
        """Get current sleep mode status
        Returns:
            dict: Result with current status
        """
        return {'status': 'Sleep mode is enabled' if self.is_sleep_mode else 'Sleep mode is disabled'}

    def is_sleep_mode_enabled(self) -> bool:
        """Check if sleep mode is enabled
        Returns:
            bool: True if sleep mode is enabled
        """
        return self.is_sleep_mode 