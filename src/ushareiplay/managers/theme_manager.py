from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.room_name_manager import RoomNameManager


class ThemeManager(Singleton):
    """Legacy adapter for room theme state.

    All behavior now lives in :class:`RoomNameManager`. New code should use
    ``RoomNameManager.instance()`` directly.
    """

    def __init__(self):
        self._room_name_manager = None

    @property
    def _room_name(self):
        if self._room_name_manager is None:
            self._room_name_manager = RoomNameManager.instance()
        return self._room_name_manager

    def get_current_theme(self):
        return self._room_name.get_current_theme()

    def set_theme(self, theme: str):
        return self._room_name.set_theme(theme)

    def can_update_now(self):
        return self._room_name.can_update_now()

    def get_remaining_cooldown_minutes(self):
        return self._room_name.get_remaining_cooldown_minutes()

    def update_last_update_time(self):
        self._room_name._advance_cooldown()

    def has_pending_ui_update(self):
        return self._room_name.has_pending_ui_update()

    def clear_pending_ui_update(self):
        self._room_name.clear_pending_ui_update()

    def initialize_from_ui(self):
        return self._room_name.initialize_from_ui()

    def verify_theme(self, expected_theme: str):
        return self._room_name.verify_theme(expected_theme)

    def reset_theme(self):
        return self._room_name.reset_theme()

    # Legacy attributes that outside code reads directly
    @property
    def current_theme(self):
        return self._room_name.current_theme

    @property
    def last_update_time(self):
        return self._room_name.last_update_time

    @property
    def cooldown_minutes(self):
        return self._room_name.cooldown_minutes

    @property
    def is_initialized(self):
        return self._room_name.is_initialized

    @property
    def pending_ui_update(self):
        return self._room_name.pending_ui_update
