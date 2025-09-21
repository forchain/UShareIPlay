import time
import traceback

from ..core.singleton import Singleton


class TitleManager(Singleton):
    def __init__(self):
        # 延迟初始化 handler 和 theme_manager，避免循环依赖
        self._handler = None
        self._theme_manager = None
        self._logger = None
        self._notice_manager = None

        self.current_title = None
        self.next_title = None
        self.is_initialized = False

        # 延迟初始化 UI，避免在初始化时调用 handler
        self._ui_initialized = False
        
        # Notice 恢复状态
        self.pending_notice_restore = False
        self.restore_notice_content = None

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def theme_manager(self):
        """延迟获取 ThemeManager 实例"""
        if self._theme_manager is None:
            from .theme_manager import ThemeManager
            self._theme_manager = ThemeManager.instance()
        return self._theme_manager

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    @property
    def notice_manager(self):
        """延迟获取 NoticeManager 实例"""
        if self._notice_manager is None:
            from .notice_manager import NoticeManager
            self._notice_manager = NoticeManager.instance()
        return self._notice_manager


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
                        # 只有在没有待更新主题的情况下才从 UI 初始化
                        if not self.theme_manager.pending_ui_update:
                            init_result = self.theme_manager.initialize_from_ui()
                            if 'error' not in init_result:
                                self.logger.info(f"Initialized theme from UI: {theme_part}")
                        else:
                            self.logger.info(
                                "Theme manager has pending update, skipping UI initialization to preserve new theme")
                    else:
                        self.logger.info(
                            f"Theme manager already initialized, keeping current theme: {self.theme_manager.get_current_theme() if self.theme_manager else 'None'}")

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

    def _check_notice_reset(self):
        """检查房间notice是否被系统重置，如果是则标记需要恢复
        Returns:
            dict: 检查结果
        """
        try:
            # 获取当前房间notice
            notice_element = self.handler.wait_for_element_plus('chat_room_notice')
            if not notice_element:
                self.logger.info("Chat room notice element not found, skipping notice check")
                return {'skipped': 'Notice element not found'}

            current_notice = self.handler.get_element_text(notice_element)
            if not current_notice:
                self.logger.info("Current notice is empty, skipping notice check")
                return {'skipped': 'Current notice is empty'}

            self.logger.info(f"Current room notice: {current_notice}")

            # 获取系统默认notice列表
            from ..core.config_loader import ConfigLoader
            config = ConfigLoader.load_config()
            system_notices = config.get('soul', {}).get('system_default_notices', [])
            
            if not system_notices:
                self.logger.warning("No system default notices configured, skipping notice check")
                return {'skipped': 'No system notices configured'}

            # 检查当前notice是否包含任何系统默认notice
            is_system_reset = False
            found_system_notice = None
            for system_notice in system_notices:
                if system_notice in current_notice:
                    is_system_reset = True
                    found_system_notice = system_notice
                    self.logger.warning(f"Found system default notice in current notice: {system_notice}")
                    break

            if not is_system_reset:
                self.logger.info("Current notice is not system reset, no need to restore")
                # 清除之前的恢复标记
                self.pending_notice_restore = False
                self.restore_notice_content = None
                return {'status': 'No system reset detected'}

            # 标记需要恢复notice到默认值
            default_notice = config.get('soul', {}).get('default_notice', 'U Share I Play\n分享音乐 享受快乐')
            self.pending_notice_restore = True
            self.restore_notice_content = default_notice
            
            self.logger.info(f"System reset detected (found: '{found_system_notice}'), will restore notice after title update")
            return {'detected': True, 'found_notice': found_system_notice, 'will_restore_to': default_notice}

        except Exception as e:
            self.logger.error(f"Error checking notice reset: {str(e)}")
            return {'error': f'Error in notice check: {str(e)}'}

    def _restore_notice_if_needed(self):
        """如果需要，恢复notice到默认值
        Returns:
            dict: 恢复结果
        """
        if not self.pending_notice_restore or not self.restore_notice_content:
            return {'skipped': 'No pending notice restore'}

        try:
            self.logger.info(f"Restoring notice to: {self.restore_notice_content}")
            
            # 使用notice_manager恢复notice
            restore_result = self.notice_manager.set_notice(self.restore_notice_content)
            
            # 清除恢复标记
            self.pending_notice_restore = False
            restore_content = self.restore_notice_content
            self.restore_notice_content = None
            
            if 'error' in restore_result:
                self.logger.error(f"Failed to restore notice: {restore_result['error']}")
                return {'error': f'Failed to restore notice: {restore_result["error"]}'}
            
            self.logger.info("Successfully restored notice to default value")
            return {'success': f'Notice restored to: {restore_content}'}

        except Exception as e:
            # 清除恢复标记，即使失败也不要重复尝试
            self.pending_notice_restore = False
            self.restore_notice_content = None
            self.logger.error(f"Error restoring notice: {str(e)}")
            return {'error': f'Error in notice restore: {str(e)}'}

    def _initialize_from_ui(self):
        """Initialize title and theme from UI on startup"""
        try:
            # 延迟初始化 UI，只在需要时执行
            if not self._ui_initialized:
                self.logger.info("Title not initialized, attempting to initialize from UI")
                self._parse_title_from_ui()
                self._ui_initialized = True
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
        if not self.handler.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}

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

            # 在点击编辑入口之前，检查notice是否需要恢复
            self.logger.info("Checking room notice before editing title")
            notice_check_result = self._check_notice_reset()
            
            if 'error' in notice_check_result:
                self.logger.warning(f"Notice check failed: {notice_check_result['error']}")
            elif 'detected' in notice_check_result:
                self.logger.info("System notice reset detected, will restore after title update")
            elif 'status' in notice_check_result:
                self.logger.info(f"Notice check result: {notice_check_result['status']}")
            elif 'skipped' in notice_check_result:
                self.logger.info(f"Notice check skipped: {notice_check_result['skipped']}")

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
                    self.current_title = title
                    self.logger.info(f'UI updated successfully, current title: {self.current_title}')

                self.handler.press_back()
                self.logger.info('Hide edit title dialog')
                
                # 标题更新成功后，检查是否需要恢复notice
                notice_restore_result = self._restore_notice_if_needed()
                if 'success' in notice_restore_result:
                    self.logger.info(f"Notice restore result: {notice_restore_result['success']}")
                elif 'error' in notice_restore_result:
                    self.logger.warning(f"Notice restore failed: {notice_restore_result['error']}")
                elif 'skipped' in notice_restore_result:
                    self.logger.debug(f"Notice restore skipped: {notice_restore_result['skipped']}")
                
                return {'success': True}

            elif key == 'title_edit_confirm':
                # Update failed - still on confirm page
                go_back = self.handler.wait_for_element_plus('go_back')
                if go_back:
                    go_back.click()
                    self.logger.warning('Update title failed, going back to chat room info screen')

                self.handler.press_back()
                self.logger.info('Hide edit title dialog')
                
                # 标题更新失败，清除notice恢复标记
                self.pending_notice_restore = False
                self.restore_notice_content = None
                
                return {'error': 'Update failed - still in cooldown period'}
            else:
                self.logger.warning('Failed to update title, unknown error')
                self.handler.press_back()
                
                # 标题更新失败，清除notice恢复标记
                self.pending_notice_restore = False
                self.restore_notice_content = None
                
                return {'error': 'Failed to update title, unknown error'}

        except Exception:
            self.logger.error(f"Error in title update: {traceback.format_exc()}")
            
            # 异常情况下，清除notice恢复标记
            self.pending_notice_restore = False
            self.restore_notice_content = None
            
            return {'error': f'Failed to update title: {title}'}
