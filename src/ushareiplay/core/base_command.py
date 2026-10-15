from abc import ABC, abstractmethod
import time
import traceback


class BaseCommand(ABC):
    """Deep base class that owns the command shell.

    Subclasses implement do_process() with only their decision logic.
    The concrete process() wrapper provides, driven by class attributes:
      - playback_muting: declare the command as a song-switching operation so
        CommandManager runs it inside PlaybackMuting's mute/readiness lifecycle
      - handler_attr: 'soul_handler' | 'music_handler', exposed as self.handler
      - error_message: template (may contain {error}) returned when do_process raises
    """

    playback_muting = False
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
        self._playlist_adoption = None
        self._mic_manager = None
        self._message_dispatch = None

    async def process(self, message_info, parameters):
        """Command shell: do_process -> exception-to-error mapping.

        Microphone lifecycle for playback commands is owned by PlaybackMuting,
        which CommandManager applies around command execution.

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

    def playback_expected_song(self, parameters):
        """播放静音保护期间用于校验播放就绪的目标歌曲。

        返回 None 表示只校验底层播放状态，不校验曲目元数据。
        """
        return None

    def playback_muting_applies(self, parameters) -> bool:
        """本次调用是否需要命令级的播放静音保护。

        默认就是类属性 `playback_muting` —— 声明参与静音的命令整体参与。
        一个命令内部有多条播放路径、且只有部分路径已迁到 `MusicManager.play()`
        时覆盖本方法：迁走的那条由引擎在守护通过后自己闭麦，提前闭麦会在
        守护拒绝时留下一次无来由的静音。
        """
        return bool(getattr(self, "playback_muting", False))

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
            from ushareiplay.managers.info_manager import InfoManager
            self._info_manager = InfoManager.instance()
        return self._info_manager

    @property
    def room_profile_manager(self):
        if self._room_profile_manager is None:
            from ushareiplay.managers.room_profile import RoomProfileManager
            self._room_profile_manager = RoomProfileManager.instance()
        return self._room_profile_manager

    @property
    def music_manager(self):
        if self._music_manager is None:
            from ushareiplay.managers.music_manager import MusicManager
            self._music_manager = MusicManager.instance()
        return self._music_manager

    @property
    def playlist_adoption(self):
        if self._playlist_adoption is None:
            from ushareiplay.managers.playlist_adoption import PlaylistAdoption
            self._playlist_adoption = PlaylistAdoption.instance()
        return self._playlist_adoption

    @property
    def mic_manager(self):
        if self._mic_manager is None:
            from ushareiplay.managers.mic_manager import MicManager
            self._mic_manager = MicManager.instance()
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
