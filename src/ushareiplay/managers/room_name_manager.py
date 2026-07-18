import logging
import time
import traceback
from datetime import datetime

from ushareiplay.core.singleton import Singleton


class RoomNameManager(Singleton):
    """Deep module that owns the room-name invariant: {theme}｜{title}.

    This is the single place that knows about the shared cooldown, pending
    theme/title state, the Soul UI write, and notice restoration. Commands,
    events, and the legacy ThemeManager/TitleManager adapters are seams around
    it.
    """

    def __init__(self):
        self._handler = None
        self._logger = None
        self._notice_manager = None

        # Theme state
        self.current_theme = "享乐"
        self.last_update_time = None
        self.cooldown_minutes = 10
        self.pending_ui_update = False

        # Title state
        self.current_title = None
        self.next_title = None
        self.is_initialized = False
        self._ui_initialized = False

        # Notice restore state
        self.pending_notice_restore = False
        self.restore_notice_content = None

    @property
    def handler(self):
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    @property
    def notice_manager(self):
        if self._notice_manager is None:
            from ushareiplay.managers.notice_manager import NoticeManager
            self._notice_manager = NoticeManager.instance()
        return self._notice_manager

    # ------------------------------------------------------------------
    # Theme API
    # ------------------------------------------------------------------

    def get_current_theme(self):
        return self.current_theme

    def set_theme(self, theme: str):
        if len(theme) > 2:
            return {'error': '主题最多两个字符'}

        new_theme = theme.strip()
        if not new_theme:
            return {'error': '主题不能为空'}

        old_theme = self.current_theme
        if old_theme != new_theme:
            self.current_theme = new_theme
            self.pending_ui_update = True
            self.logger.info(f'Theme updated from {old_theme} to {new_theme}, pending UI update')
        else:
            self.logger.info(f'Theme unchanged: {new_theme}')

        return {
            'success': True,
            'theme': new_theme,
            'old_theme': old_theme
        }

    def can_update_now(self):
        if not self.last_update_time:
            return True
        return (datetime.now() - self.last_update_time).total_seconds() >= self.cooldown_minutes * 60

    def get_remaining_cooldown_minutes(self):
        if not self.last_update_time:
            return 0
        remaining_seconds = self.cooldown_minutes * 60 - (datetime.now() - self.last_update_time).total_seconds()
        return max(0, int(remaining_seconds / 60))

    def _advance_cooldown(self):
        self.last_update_time = datetime.now()
        self.logger.info(f'Updated room-name cooldown time to {self.last_update_time}')

    def has_pending_ui_update(self):
        return self.pending_ui_update

    def clear_pending_ui_update(self):
        self.pending_ui_update = False
        self.logger.info('Cleared pending theme UI update flag')

    def initialize_from_ui(self):
        if self.is_initialized:
            self.logger.info("Room name already initialized, skipping UI initialization")
            return {'success': True, 'theme': self.current_theme, 'already_initialized': True}

        room_title_text = self.get_room_title_text_from_ui()
        if not room_title_text:
            return {'error': 'Room title element or text not found'}

        if '｜' in room_title_text:
            parts = room_title_text.split('｜', 1)
            if len(parts) == 2:
                theme_part = parts[0].strip()
                self.current_theme = theme_part
                self.current_title = parts[1].strip()
                self.is_initialized = True
                self.logger.info(f'Initialized room name from UI: theme={theme_part}, title={self.current_title}')
                return {'success': True, 'theme': theme_part, 'title': self.current_title, 'initialized': True}

        self.current_title = room_title_text
        self.is_initialized = True
        self.logger.info(f'Initialized title from UI (no theme): {room_title_text}')
        return {'success': True, 'title': room_title_text, 'initialized': True}

    def verify_theme(self, expected_theme: str):
        if self.current_theme == expected_theme:
            self.logger.info(f'Theme verification passed: {expected_theme}')
            return {'success': True, 'theme': self.current_theme}
        self.logger.error(f'Theme verification failed: expected {expected_theme}, got {self.current_theme}')
        return {'error': f'Theme verification failed: expected {expected_theme}, got {self.current_theme}'}

    def reset_theme(self):
        return self.set_theme("享乐")

    # ------------------------------------------------------------------
    # Title API
    # ------------------------------------------------------------------

    def get_current_title(self):
        return self.current_title

    def get_next_title(self):
        return self.next_title

    def get_title_to_update(self):
        if self.next_title:
            return self.next_title
        if self.current_title:
            return self.current_title
        if not self.is_initialized:
            return self._parse_title_from_ui()
        return None

    def _parse_title_from_ui(self):
        room_title_text = self.get_room_title_text_from_ui()
        if not room_title_text:
            return None

        self.logger.info(f"Found room title in UI: {room_title_text}")
        if '｜' in room_title_text:
            parts = room_title_text.split('｜', 1)
            if len(parts) == 2:
                self.current_theme = parts[0].strip()
                self.current_title = parts[1].strip()
                self.is_initialized = True
                self.logger.info(f"Initialized room name from UI: theme={self.current_theme}, title={self.current_title}")
                return self.current_title

        self.current_title = room_title_text
        self.is_initialized = True
        self.logger.info(f"Initialized title from UI (no theme): {room_title_text}")
        return room_title_text

    def get_room_title_text_from_ui(self):
        try:
            room_title_element = self.handler.element_finder.try_find_element('chat_room_title', log=False)
            if not room_title_element:
                return None
            text = self.handler.element_finder.get_element_text(room_title_element)
            return (text or "").strip() or None
        except Exception:
            return None

    def set_next_title(self, title: str, theme: str = None):
        if theme:
            theme_result = self.set_theme(theme)
            if 'error' in theme_result:
                return theme_result

        new_title = title.split('|')[0].split('(')[0].strip()[:12]
        self.next_title = new_title

        if not self.can_update_now():
            remaining_minutes = self.get_remaining_cooldown_minutes()
            self.logger.info(f'Title will be updated to {new_title} in {remaining_minutes} minutes')
            return {'title': f'{new_title}. Title will update in {remaining_minutes} minutes'}

        self.logger.info(f'Title will be updated to {new_title} soon')
        return {'title': f'{new_title}. Title will update soon'}

    # ------------------------------------------------------------------
    # Combined update
    # ------------------------------------------------------------------

    def process_pending_update(self):
        """Apply any pending theme/title change if the cooldown allows.

        Returns:
            dict with keys describing what happened:
            - 'ui_updated': True if the UI was written
            - 'error': if the attempt failed
            - 'cooldown': True if skipped due to cooldown
            - 'skipped': True if nothing was pending
            - 'current_title': the title after a successful update
        """
        # Do not inspect the UI just to discover that there is no work queued.
        # The monitoring loop calls this method every cycle; UI reads belong
        # only to an actual pending title/theme update.
        if not self.next_title and not self.pending_ui_update:
            return {'skipped': True, 'reason': 'no pending update'}

        if not self.can_update_now():
            return {'cooldown': True, 'remaining_minutes': self.get_remaining_cooldown_minutes()}

        title_to_update = self.get_title_to_update()
        if not title_to_update:
            return {'skipped': True, 'reason': 'no title to update'}

        result = self._update_title_ui(title_to_update)
        self._advance_cooldown()

        if 'error' not in result:
            self.clear_pending_ui_update()
            return {'ui_updated': True, 'current_title': self.current_title}
        return {'error': result['error']}

    def _update_title_ui(self, title: str):
        """Single attempt to write the room name to the Soul UI."""
        try:
            result = self.handler.ui_actions.switch_and_click(
                'chat_room_title', error_message='Failed to find room title'
            )
            if 'error' in result:
                return result

            current_theme = self.current_theme
            self.logger.info(f"Updating room title: {current_theme}｜{title}")

            notice_check_result = self._check_notice_reset()
            if 'error' in notice_check_result:
                self.logger.warning(f"Notice check failed: {notice_check_result['error']}")
            elif 'detected' in notice_check_result:
                self.logger.info("System notice reset detected, will restore after title update")

            edit_entry = self.handler.element_finder.wait_for_element_clickable('title_edit_entry')
            if not edit_entry:
                return {'error': 'Failed to find edit title entry'}
            if not self.handler.gesture_handler.click_element_at(edit_entry, y_ratio=0.25):
                return {'error': 'Failed to click edit entry'}

            title_input = self.handler.element_finder.wait_for_element_clickable('title_edit_input')
            if not title_input:
                return {'error': 'Failed to find title input'}
            title_input.clear()
            title_input.send_keys(f"{current_theme}｜" + title)

            confirm = self.handler.element_finder.wait_for_element_clickable('title_edit_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            time.sleep(1)

            key, element = self.handler.element_finder.wait_for_any_element(['title_edit_entry', 'title_edit_confirm'])

            if key == 'title_edit_entry':
                if self.next_title:
                    self.current_title = self.next_title
                    self.next_title = None
                else:
                    self.current_title = title
                self.logger.info(f'Updated current title to {self.current_title}')

                self.handler.key_actions.press_back()
                self.logger.info('Hide edit title dialog')

                room_title_text = self.get_room_title_text_from_ui()
                if room_title_text and '｜' not in room_title_text:
                    if not (self.next_title == '日推' and not self.can_update_now()):
                        self.next_title = '日推'
                        self.logger.info(
                            f'房名未包含分隔符｜(当前: {room_title_text!r})，可能审核未通过，已排队重设为 日推'
                        )

                self._restore_notice_if_needed()
                return {'success': True}

            if key == 'title_edit_confirm':
                go_back = self.handler.element_finder.wait_for_element('go_back')
                if go_back:
                    go_back.click()
                self.handler.key_actions.press_back()
                self._restore_notice_if_needed()
                self.pending_notice_restore = False
                self.restore_notice_content = None
                return {'error': 'Update failed - still in cooldown period'}

            self.handler.key_actions.press_back()
            self.pending_notice_restore = False
            self.restore_notice_content = None
            return {'error': 'Failed to update title, unknown error'}

        except Exception:
            self.logger.error(f"Error in title update: {traceback.format_exc()}")
            self.pending_notice_restore = False
            self.restore_notice_content = None
            return {'error': f'Failed to update title: {title}'}

    # ------------------------------------------------------------------
    # Notice restore
    # ------------------------------------------------------------------

    def _check_notice_reset(self):
        try:
            notice_element = self.handler.element_finder.wait_for_element('chat_room_notice')
            if not notice_element:
                return {'skipped': 'Notice element not found'}

            current_notice = self.handler.element_finder.get_element_text(notice_element)
            if not current_notice:
                return {'skipped': 'Current notice is empty'}

            self.logger.info(f"Current room notice: {current_notice}")

            from ushareiplay.core.config_loader import ConfigLoader
            config = ConfigLoader.load_config()
            system_notices = config.get('soul', {}).get('system_default_notices', [])
            if not system_notices:
                return {'skipped': 'No system notices configured'}

            for system_notice in system_notices:
                if system_notice in current_notice:
                    default_notice = config.get('soul', {}).get('default_notice', 'U Share I Play\n分享音乐 享受快乐')
                    self.pending_notice_restore = True
                    self.restore_notice_content = default_notice
                    return {
                        'detected': True,
                        'found_notice': system_notice,
                        'will_restore_to': default_notice
                    }

            self.pending_notice_restore = False
            self.restore_notice_content = None
            return {'status': 'No system reset detected'}

        except Exception as e:
            self.logger.error(f"Error checking notice reset: {str(e)}")
            return {'error': f'Error in notice check: {str(e)}'}

    def _restore_notice_if_needed(self):
        if not self.pending_notice_restore or not self.restore_notice_content:
            return {'skipped': 'No pending notice restore'}

        try:
            self.logger.info(f"Restoring notice to: {self.restore_notice_content}")
            restore_result = self.notice_manager.set_notice(self.restore_notice_content)

            self.pending_notice_restore = False
            restore_content = self.restore_notice_content
            self.restore_notice_content = None

            if 'cooldown' in restore_result:
                return {'cooldown': True, 'remaining_minutes': restore_result.get('remaining_minutes', 0)}
            if 'error' in restore_result:
                self.logger.error(f"Failed to restore notice: {restore_result['error']}")
                return {'error': f'Failed to restore notice: {restore_result["error"]}'}
            if 'success' in restore_result:
                return {'success': f'Notice restored to: {restore_content}'}
            return restore_result

        except Exception as e:
            self.pending_notice_restore = False
            self.restore_notice_content = None
            self.logger.error(f"Error restoring notice: {str(e)}")
            return {'error': f'Error in notice restore: {str(e)}'}
