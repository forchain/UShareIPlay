from abc import ABC, abstractmethod
import time
import traceback


class BaseCommand(ABC):
    """Deep base class that owns the command shell.

    Subclasses implement do_process() with only their decision logic.
    The concrete process() wrapper provides, driven by class attributes:
      - handler_attr: 'soul_handler' | 'music_handler', exposed as self.handler
      - error_message: template (may contain {error}) returned when do_process raises

    Playback muting is owned by MusicManager (ADR-0007); commands declare nothing.
    """

    handler_attr = None
    error_message = 'Failed to process command: {error}'

    def __init__(self, controller):
        self.controller = controller
        self.soul_handler = controller.soul_handler
        self.music_handler = controller.music_handler
        self.handler = getattr(controller, self.handler_attr) if self.handler_attr else None
        self.last_update_time = time.time()
        self._info_manager = None
        self._room_profile_manager = None
        self._music_manager = None
        self._playlist_session = None
        self._mic_manager = None
        self._message_dispatch = None

    async def process(self, message_info, parameters):
        """Command shell: do_process -> exception-to-error mapping.

        Args:
            message_info: MessageInfo object containing message details
            parameters: list of command parameters
        Returns:
            dict: result from do_process, or {'error': ...} on failure
        """
        try:
            return await self.do_process(message_info, parameters)
        except Exception as e:
            self.soul_handler.log_error(
                f"Error processing {type(self).__name__}: {traceback.format_exc()}")
            error_result = {'error': self.error_message.format(error=e)}
            error_result.update(self.error_context(message_info, parameters))
            return error_result

    def error_context(self, message_info, parameters):
        """Extra fields merged into the error result when do_process raises.

        Override when the command's error_template references extra fields
        (e.g. room's {party_id}).
        """
        return {}

    @abstractmethod
    async def do_process(self, message_info, parameters):
        """Command decision logic. Implemented by subclasses."""
        pass

    def coerce_int(self, value, min_value=None, max_value=None, error='Invalid number'):
        """Coerce a string parameter to int with an optional inclusive range check.

        Returns:
            (number, None) on success, or (None, error_message) on failure
        """
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None, error
        if min_value is not None and number < min_value:
            return None, error
        if max_value is not None and number > max_value:
            return None, error
        return number, None

    @property
    def info_manager(self):
        if self._info_manager is None:
            self._info_manager = self.controller.info_manager
        return self._info_manager

    @property
    def room_profile_manager(self):
        if self._room_profile_manager is None:
            self._room_profile_manager = self.controller.room_profile_manager
        return self._room_profile_manager

    @property
    def music_manager(self):
        if self._music_manager is None:
            from ushareiplay.managers.music_manager import MusicManager
            self._music_manager = MusicManager.instance()
        return self._music_manager

    @property
    def playlist_session(self):
        if self._playlist_session is None:
            self._playlist_session = self.controller.playlist_session
        return self._playlist_session

    @property
    def mic_manager(self):
        if self._mic_manager is None:
            self._mic_manager = self.controller.mic_control
        return self._mic_manager

    @property
    def message_dispatch(self):
        if self._message_dispatch is None:
            from ushareiplay.core.message_dispatch import MessageDispatch

            self._message_dispatch = MessageDispatch.instance().bind_handler(self.soul_handler)
        return self._message_dispatch

    def update(self):
        """Update method called every monitoring loop
        Can be overridden by commands that need timer functionality

        Returns:
            None
        """
        current_time = time.time()
        delta_time = current_time - self.last_update_time
        self.last_update_time = current_time

        # Override this method in commands that need updates
        pass

    async def user_enter(self, username: str):
        """Called when a user enters the party
        Args:
            username: str, name of the user who entered
        Returns:
            None
        """
        # Override this method in commands that need to handle user entry
        pass
