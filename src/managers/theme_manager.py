import traceback
from datetime import datetime, timedelta
from typing import Optional, Tuple

class ThemeManager:
    _instance = None

    def __new__(cls, handler=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.handler = handler
            cls._instance.last_update_time = None
            cls._instance.current_mode = None
            cls._instance.current_title = None
            cls._instance.next_mode = None
            cls._instance.next_title = None
            cls._instance.cooldown_minutes = 15 + 2
        return cls._instance

    def change_theme(self, mode: Optional[str] = None, title: Optional[str] = None) -> dict:
        """Change room theme with cooldown check
        Args:
            mode: Optional[str], new mode text (2 chars)
            title: Optional[str], new title text (12 chars)
        Returns:
            dict: Result with theme info or error
        """
        # Switch to Soul app first
        if not self.handler.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        self.handler.logger.info("Switched to Soul app")

        # Process mode and title
        if mode:
            self.next_mode = mode[:2]
        if title:
            self.next_title = title[:12]

        current_time = datetime.now()

        if not self.last_update_time:
            self.handler.logger.info(f'Theme will be updated to {self._format_theme()} soon')
            return {
                'theme': f'{self._format_theme()}. Theme will update soon'
            }

        time_diff = current_time - self.last_update_time
        remaining_minutes = self.cooldown_minutes - (time_diff.total_seconds() / 60)
        if remaining_minutes < 0:
            self.handler.logger.info(f'Theme will be updated to {self._format_theme()} soon')
            return {
                'theme': f'{self._format_theme()}. Theme will update soon'
            }

        self.handler.logger.info(f'Theme will be updated to {self._format_theme()} in {remaining_minutes} minutes')
        return {
            'theme': f'{self._format_theme()}. Theme will update in {int(remaining_minutes)} minutes'
        }

    def _format_theme(self) -> str:
        """Format current theme as mode|title"""
        mode = self.next_mode if self.next_mode else self.current_mode
        title = self.next_title if self.next_title else self.current_title
        return f"{mode}|{title}" if mode and title else ""

    def update(self):
        """Check and update theme periodically"""
        try:
            if not self.next_mode and not self.next_title:
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
            result = self._update_theme()
            if not 'error' in result:
                self.handler.logger.info(f'Theme is updated to {self._format_theme()}')
                self.handler.send_message(
                    f"Updating theme to {self._format_theme()}"
                )

        except Exception as e:
            self.handler.log_error(f"Error in theme update: {traceback.format_exc()}")

    def _update_theme(self) -> dict:
        """Update room theme
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

            # Input new theme
            title_input = self.handler.wait_for_element_clickable_plus('title_edit_input')
            if not title_input:
                return {'error': 'Failed to find title input'}
            title_input.clear()
            title_input.send_keys(self._format_theme())

            # Click confirm
            confirm = self.handler.wait_for_element_clickable_plus('title_edit_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            current_time = datetime.now()
            self.last_update_time = current_time
            self.handler.logger.info(f'updated last theme update time to {current_time}')
            self.current_mode = self.next_mode
            self.current_title = self.next_title
            self.next_mode = None
            self.next_title = None

            title_edit_entry = self.handler.wait_for_element_plus('title_edit_entry')
            if title_edit_entry:
                self.handler.logger.info('wait for title edit entry')
            else:
                go_back = self.handler.wait_for_element_plus('go_back')
                if go_back:
                    go_back.click()
                    self.handler.logger.info('go back to chat room info screen')

            self.handler.press_back()
            self.handler.logger.info('Hide edit theme dialog')

            return {'success': True}

        except Exception as e:
            self.handler.log_error(f"Error in theme update: {traceback.format_exc()}")
            return {'error': f'Failed to update theme: {self._format_theme()}'} 