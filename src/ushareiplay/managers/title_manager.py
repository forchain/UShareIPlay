from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.room_name_manager import RoomNameManager


class TitleManager(Singleton):
    """Legacy adapter for room title state.

    All behavior now lives in :class:`RoomNameManager`. New code should use
    ``RoomNameManager.instance()`` directly.
    """

    def __init__(self):
        self._room_name_manager = None
        self._theme_manager = None

    @property
    def _room_name(self):
        if self._room_name_manager is None:
            self._room_name_manager = RoomNameManager.instance()
        return self._room_name_manager

    @property
    def theme_manager(self):
        """Legacy seam: some callers still read ``title_manager.theme_manager``."""
        if self._theme_manager is None:
            from ushareiplay.managers.theme_manager import ThemeManager
            self._theme_manager = ThemeManager.instance()
        return self._theme_manager

    def get_current_title(self):
        return self._room_name.get_current_title()

    def get_next_title(self):
        return self._room_name.get_next_title()

    def get_title_to_update(self):
        return self._room_name.get_title_to_update()

    def get_room_title_text_from_ui(self):
        return self._room_name.get_room_title_text_from_ui()

    def set_next_title(self, title: str):
        return self._room_name.set_next_title(title)

    def can_update_now(self):
        return self._room_name.can_update_now()

    def update_title_ui(self, title: str, theme: str = None):
        return self._room_name._update_title_ui(title)

    # Legacy attributes that outside code reads directly
    @property
    def current_title(self):
        return self._room_name.current_title

    @current_title.setter
    def current_title(self, value):
        self._room_name.current_title = value

    @property
    def next_title(self):
        return self._room_name.next_title

    @next_title.setter
    def next_title(self, value):
        self._room_name.next_title = value

    @property
    def is_initialized(self):
        return self._room_name.is_initialized

    @property
    def pending_notice_restore(self):
        return self._room_name.pending_notice_restore

    @property
    def restore_notice_content(self):
        return self._room_name.restore_notice_content
