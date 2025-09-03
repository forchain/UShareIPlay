import time
import traceback
import logging

from ..core.singleton import Singleton

class TitleManager(Singleton):
    def __init__(self, handler):
        self.handler = handler
        self.logger = logging.getLogger('title_manager')
        # Get ThemeManager singleton instance
        from .theme_manager import ThemeManager
        self.theme_manager = ThemeManager.instance(handler)
        
        self.current_title = None
        self.next_title = None
        self.is_initialized = False
        

        
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
        # Always prioritize next_title over current_title
        if self.next_title:
            return self.next_title
        elif self.current_title:
            return self.current_title
        
        # If both are empty and not initialized, try to parse from UI (only for initial setup)
        if not self.is_initialized:
            return self._parse_title_from_ui()
        
        # If initialized but no title set, return None
        return None

    def _parse_title_from_ui(self):
        """Parse current title from UI (only for initialization)
        Returns:
            str: Parsed title or None if failed
        """
        if self.is_initialized:
            self.logger.info("Title already initialized, skipping UI parsing")
            return self.current_title

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
                    
                    # Initialize theme manager if available and not already initialized
                    if self.theme_manager and not self.theme_manager.is_initialized:
                        init_result = self.theme_manager.initialize_from_ui()
                        if 'error' not in init_result:
                            self.logger.info(f"Initialized theme from UI: {theme_part}")
                    else:
                        self.logger.info(f"Theme manager already initialized, keeping current theme: {self.theme_manager.get_current_theme() if self.theme_manager else 'None'}")
                    
                    # Set current title
                    self.current_title = title_part
                    self.is_initialized = True
                    self.logger.info(f"Initialized current title from UI: {title_part}")
                    
                    return title_part
            
            # If no separator found, treat the whole text as title
            self.current_title = room_title_text
            self.is_initialized = True
            self.logger.info(f"Initialized current title from UI (no theme): {room_title_text}")
            return room_title_text
            
        except Exception as e:
            self.logger.error(f"Error parsing title from UI: {str(e)}")
            return None

    def _initialize_from_ui(self):
        """Initialize title and theme from UI on startup"""
        try:
            # Only initialize if not already initialized
            if not self.is_initialized:
                self.logger.info("Title not initialized, attempting to initialize from UI")
                self._parse_title_from_ui()
            else:
                self.logger.info("Title already initialized, skipping UI initialization")
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

        # Update title
        self.next_title = new_title

        # Check cooldown using shared theme manager
        if self.theme_manager and not self.theme_manager.can_update_now():
            remaining_minutes = self.theme_manager.get_remaining_cooldown_minutes()
            self.logger.info(f'Title will be updated to {new_title} in {remaining_minutes} minutes')
            return {
                'title': f'{new_title}. Title will update in {remaining_minutes} minutes'
            }

        self.logger.info(f'Title will be updated to {new_title} soon')
        return {
            'title': f'{new_title}. Title will update soon'
        }

    def can_update_now(self):
        """Check if title can be updated now (not in cooldown)
        Returns:
            bool: True if can update, False if in cooldown
        """
        if self.theme_manager:
            return self.theme_manager.can_update_now()
        return True



    def update_title_ui(self, title: str, theme: str = None):
        """Update room title in UI (single attempt, no retry logic here)
        Args:
            title: New title text
            theme: Theme to use (optional, will use current theme if not provided)
        Returns:
            dict: Result with error or success
        """
        try:
            # Always prioritize theme_manager data over any other source
            if self.theme_manager:
                current_theme = self.theme_manager.get_current_theme()
                self.logger.info(f"Using theme from theme_manager: {current_theme}")
                # Only update theme_manager if explicitly provided and different
                if theme and theme != current_theme:
                    self.theme_manager.set_theme(theme)
                    current_theme = theme
                    self.logger.info(f"Updated theme_manager to use provided theme: {theme}")
            else:
                # Fallback if no theme_manager
                current_theme = theme if theme else "享乐"
                self.logger.info(f"Using fallback theme (no theme_manager): {current_theme}")
            
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
            title_input.send_keys(f"{current_theme}｜" + title)
            
            # Click confirm
            confirm = self.handler.wait_for_element_clickable_plus('title_edit_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            # Wait 1 second to ensure UI has updated
            time.sleep(1)

            # Check if update was successful by looking for edit entry or confirm button
            key, element = self.handler.wait_for_any_element_plus(['title_edit_entry', 'title_edit_confirm'])
            
            if key == 'title_edit_entry':
                # Update successful - we're back to edit entry page
                if self.next_title:
                    self.current_title = self.next_title
                    self.next_title = None
                    self.logger.info(f'Updated current title to {self.current_title}')
                else:
                    # Even if no next_title, the UI was updated successfully
                    # This happens when theme is updated but title remains the same
                    self.logger.info(f'UI updated successfully, current title: {self.current_title}')
                
                self.handler.press_back()
                self.logger.info('Hide edit title dialog')
                return {'success': True}
                
            elif key == 'title_edit_confirm':
                # Update failed - still on confirm page
                go_back = self.handler.wait_for_element_plus('go_back')
                if go_back:
                    go_back.click()
                    self.logger.warning('Update title failed, going back to chat room info screen')
                
                self.handler.press_back()
                self.logger.info('Hide edit title dialog')
                return {'error': 'Update failed - still in cooldown period'}
            else:
                self.logger.warning('Failed to update title, unknown error')
                self.handler.press_back()
                return {'error': 'Failed to update title, unknown error'}

        except Exception:
            self.logger.error(f"Error in title update: {traceback.format_exc()}")
            return {'error': f'Failed to update title: {title}'}


