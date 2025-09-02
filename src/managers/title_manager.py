import time
import traceback
import logging
from datetime import datetime

class TitleManager:
    def __init__(self, handler, theme_manager=None):
        self.handler = handler
        self.logger = logging.getLogger('title_manager')
        self.theme_manager = theme_manager
        
        self.last_update_time = None
        self.current_title = None
        self.next_title = None
        self.cooldown_minutes = 10 + 2
        
        # Initialize from UI if no title is set
        self._initialize_from_ui()

    def get_current_title(self):
        """Get current title
        Returns:
            str: Current title or None if not set
        """
        return self.current_title

    def get_next_title(self):
        """Get next title
        Returns:
            str: Next title or None if not set
        """
        return self.next_title

    def get_title_to_update(self):
        """Get title that should be used for update
        Returns:
            str: Current title or next title, or None if neither is set
        """
        # If we have current or next title, return it
        if self.current_title or self.next_title:
            return self.current_title or self.next_title
        
        # If both are empty, try to parse from UI (for newly created rooms)
        return self._parse_title_from_ui()

    def _parse_title_from_ui(self):
        """Parse current title from UI
        Returns:
            str: Parsed title or None if failed
        """
        try:
            # Find room title element
            room_title_element = self.handler.try_find_element_plus('chat_room_title', log=False)
            if not room_title_element:
                self.logger.info("Room title element not found")
                return None
            
            # Get room title text
            room_title_text = self.handler.get_element_text(room_title_element)
            if not room_title_text:
                self.logger.info("Room title text is empty")
                return None
            
            self.logger.info(f"Found room title in UI: {room_title_text}")
            
            # Parse theme and title from room name
            # Expected format: "主题｜标题"
            if '｜' in room_title_text:
                parts = room_title_text.split('｜', 1)
                if len(parts) == 2:
                    theme_part = parts[0].strip()
                    title_part = parts[1].strip()
                    
                    # Update theme manager if available
                    if self.theme_manager:
                        self.theme_manager.set_theme(theme_part)
                        self.logger.info(f"Updated theme from UI: {theme_part}")
                    
                    # Set current title
                    self.current_title = title_part
                    self.logger.info(f"Updated current title from UI: {title_part}")
                    
                    return title_part
            
            # If no separator found, treat the whole text as title
            self.current_title = room_title_text
            self.logger.info(f"Updated current title from UI (no theme): {room_title_text}")
            return room_title_text
            
        except Exception as e:
            self.logger.error(f"Error parsing title from UI: {str(e)}")
            return None

    def _initialize_from_ui(self):
        """Initialize title and theme from UI on startup"""
        try:
            # Only initialize if we don't have any title set
            if not self.current_title and not self.next_title:
                self.logger.info("No title set, attempting to initialize from UI")
                self._parse_title_from_ui()
            else:
                self.logger.info("Title already set, skipping UI initialization")
        except Exception as e:
            self.logger.error(f"Error initializing from UI: {str(e)}")

    def set_next_title(self, title: str):
        """Set next title to be updated
        Args:
            title: str, new title text
        Returns:
            dict: Result with title info or error
        """
        # Switch to Soul app first
        if not self.handler.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        self.logger.info("Switched to Soul app")

        new_title = title.split('|')[0].split('(')[0].strip()[:12]
        current_time = datetime.now()

        # Update title
        self.next_title = new_title

        if not self.last_update_time:
            self.logger.info(f'Title will be updated to {new_title} soon')
            return {
                'title': f'{new_title}. Title will update soon'
            }

        time_diff = current_time - self.last_update_time
        remaining_minutes = self.cooldown_minutes - (time_diff.total_seconds() / 60)
        if remaining_minutes < 0:
            self.logger.info(f'Title will be updated to {new_title} soon')
            return {
                'title': f'{new_title}. Title will update soon'
            }

        self.logger.info(f'Title will be updated to {new_title} in {remaining_minutes} minutes')
        return {
            'title': f'{new_title}. Title will update in {int(remaining_minutes)} minutes'
        }

    def can_update_now(self):
        """Check if title can be updated now (not in cooldown)
        Returns:
            bool: True if can update, False if in cooldown
        """
        if not self.last_update_time:
            return True

        current_time = datetime.now()
        time_diff = current_time - self.last_update_time
        return time_diff.total_seconds() >= self.cooldown_minutes * 60

    def update_title_ui(self, title: str, theme: str = None):
        """Update room title in UI
        Args:
            title: New title text
            theme: Theme to use (optional, will sync from UI or use current theme if not provided)
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
            
            # Determine theme to use
            if theme:
                # Use provided theme
                current_theme = theme
            elif self.theme_manager:
                # Sync theme from UI first, then use it
                sync_result = self.theme_manager.sync_theme_from_ui()
                if 'error' not in sync_result:
                    current_theme = self.theme_manager.get_current_theme()
                else:
                    # Fallback to manager's current theme
                    current_theme = self.theme_manager.get_current_theme()
            else:
                # Fallback to default
                current_theme = "享乐"
            
            title_input.send_keys(f"{current_theme}｜" + title)
            
            # Store the theme that will be used for UI update
            self._ui_update_theme = current_theme

            # Click confirm
            confirm = self.handler.wait_for_element_clickable_plus('title_edit_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            current_time = datetime.now()
            self.last_update_time = current_time
            self.logger.info(
                f'Updated last title update time to {current_time}, current title: {self.current_title}, next title: {self.next_title}')
            time.sleep(1)

            key, element = self.handler.wait_for_any_element_plus(['title_edit_entry', 'title_edit_confirm'])
            if key == 'title_edit_entry':
                if self.next_title:
                    self.current_title = self.next_title
                    self.next_title = None
                    self.logger.info(f'Updated current title to {self.current_title}')
                else:
                    self.logger.warning(f'Next title is empty, skip update, current title: {self.current_title}')
                
                # Update theme manager if UI update was successful
                if hasattr(self, '_ui_update_theme') and self.theme_manager:
                    self.theme_manager.set_theme(self._ui_update_theme)
                    self.logger.info(f'Synchronized theme manager with UI update: {self._ui_update_theme}')
                    delattr(self, '_ui_update_theme')
                    
            elif key == 'title_edit_confirm':
                go_back = self.handler.wait_for_element_plus('go_back')
                if go_back:
                    go_back.click()
                    self.logger.warning('Update title too frequently, go back to chat room info screen')
            else:
                self.logger.warning('Failed to update title, unknown error')

            self.handler.press_back()
            self.logger.info('Hide edit title dialog')

            return {'success': True}

        except Exception as e:
            self.logger.error(f"Error in title update: {traceback.format_exc()}")
            return {'error': f'Failed to update title: {title}'}

    def force_update_title(self, title: str, theme: str = None):
        """Force update title (bypass cooldown)
        Args:
            title: New title text
            theme: Theme to use (optional)
        Returns:
            dict: Result with error or success
        """
        current_time = datetime.now()
        result = self.update_title_ui(title, theme)
        
        if 'error' not in result:
            # Update the last update time to prevent immediate cooldown issues
            self.last_update_time = current_time
            
        return result
