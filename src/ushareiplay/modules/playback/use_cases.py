"""播放用例：歌单会话管理、播放静音保护、点歌/切歌/下一首编排。"""

import inspect
import logging
from contextlib import contextmanager
from typing import Awaitable, Callable, Iterator, Optional, Union

from ushareiplay.modules.mic.ports import MicControl
from ushareiplay.modules.playback.domain import (
    PlaybackMode,
    PlaybackMutingPolicy,
    PlaybackMutingSettings,
    PlaybackRequest,
    PlaybackResult,
    PlaybackStatus,
    PlaylistContext,
    PlaylistGuard,
    primary_topic,
)
from ushareiplay.modules.playback.ports import (
    MediaSessionPort,
    MusicUIDriverPort,
    NextTrackPort,
    RoomProfileWriter,
)
from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.shared.roles import RolePolicy


class PlaylistSession:
    """Playlist Context + Next Queue + Playlist Guard 的唯一用例所有者。"""

    def __init__(
        self,
        config: Optional[ConfigView] = None,
        room_profile: Optional[RoomProfileWriter] = None,
        online_users: Optional[Callable[[], set[str]]] = None,
        avatar_usernames: Optional[Callable[[str], Union[set[str], Awaitable[set[str]]]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._config = config
        self._room_profile = room_profile
        self._online_users = online_users
        self._avatar_usernames = avatar_usernames
        self._logger = logger or logging.getLogger("ushareiplay.modules.playback.playlist_session")
        self._context = PlaylistContext()
        self._guard = PlaylistGuard()

    @property
    def list_mode(self) -> str:
        return self._context.list_mode

    @list_mode.setter
    def list_mode(self, value: str) -> None:
        self._context.list_mode = value

    @property
    def player_name(self) -> str:
        return self._context.player_name

    @player_name.setter
    def player_name(self, value: str) -> None:
        self._context.player_name = value
        self._logger.info(f"Player name set to: {value}")

    @property
    def current_playlist_name(self) -> Optional[str]:
        return self._context.current_playlist_name

    @current_playlist_name.setter
    def current_playlist_name(self, value: Optional[str]) -> None:
        self._context.current_playlist_name = value
        self._logger.info(f"Playlist name set to: {value}")

    def get_playlist_info(self) -> Optional[dict]:
        return self._context.get_playlist_info()

    @property
    def pending_next_count(self) -> int:
        return self._context.next_queue.pending_count

    @property
    def next_queue_contributors(self) -> set[str]:
        return self._context.next_queue.contributors

    def record_next(self, requester: str) -> None:
        if self._context.next_queue.record_next(requester):
            self._logger.info(f"Next Queue started by: {requester}")

    def consume_track(self) -> None:
        if self._context.next_queue.consume_track():
            self._logger.info("Next Queue emptied")

    def clear_next_queue(self) -> None:
        if self._context.next_queue.clear():
            self._logger.info("Next Queue cleared")

    def _online(self) -> set[str]:
        return self._online_users() if self._online_users is not None else set()

    async def _avatars(self, username: str) -> set[str]:
        if self._avatar_usernames is None:
            return {username}
        result = self._avatar_usernames(username)
        if inspect.isawaitable(result):
            return await result
        return result

    async def guard_switch(
        self,
        requester: str,
        incoming_mode: Optional[str] = None,
        config: Optional[ConfigView] = None,
    ) -> Optional[dict]:
        """歌单守护检查：非系统角色单曲点播豁免，其余交由歌单与 Next Queue 守护。"""
        role_policy = RolePolicy(config if config is not None else self._config)
        if self._guard.should_exempt_single_song(requester, incoming_mode, role_policy):
            return None
        return await self.check_playlist_protection(requester, config=config)

    async def check_playlist_protection(
        self,
        caller_nickname: str,
        config: Optional[ConfigView] = None,
    ) -> Optional[dict]:
        role_policy = RolePolicy(config if config is not None else self._config)
        if role_policy.is_human_operator(caller_nickname):
            return None

        online_users = self._online()
        player_name = self._context.player_name
        player_avatars: set[str] = {player_name} if player_name else set()
        if (
            player_name
            and not role_policy.is_privileged(player_name)
            and caller_nickname != player_name
        ):
            try:
                player_avatars = await self._avatars(player_name)
            except Exception:
                player_avatars = {player_name}

        contributor_avatars: dict[str, set[str]] = {}
        if self._context.next_queue.pending_count > 0:
            for contributor in sorted(
                c for c in self._context.next_queue.contributors if not role_policy.is_privileged(c)
            ):
                contributor_avatars[contributor] = await self._avatars(contributor)

        error = self._guard.check_protection(
            caller_nickname=caller_nickname,
            player_name=player_name,
            player_avatars=player_avatars,
            online_users=online_users,
            next_queue=self._context.next_queue,
            contributor_avatars=contributor_avatars,
            role_policy=role_policy,
        )
        return {"error": error} if error else None

    def adopt(
        self,
        requester: Optional[str],
        mode: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        playlist: Optional[str] = None,
    ) -> Optional[dict]:
        """把一次已发生的连续歌单切换同步到房间上下文（单曲跳过）。"""
        if mode == PlaybackMode.SONG.value:
            return None

        was_non_empty = self._context.next_queue.clear()
        if was_non_empty:
            self._logger.info("Next Queue cleared")

        if requester:
            self.player_name = requester
        self.list_mode = mode
        if playlist is not None:
            self.current_playlist_name = playlist

        if self._room_profile is None:
            return None

        title_value = (title or "").strip()
        if title_value:
            title_result = self._room_profile.set_title(title_value)
            if isinstance(title_result, dict) and "error" in title_result:
                return title_result

        topic_value = primary_topic(topic)
        if topic_value:
            topic_result = self._room_profile.set_topic(topic_value)
            if isinstance(topic_result, dict) and "error" in topic_result:
                return topic_result

        return None


class PlaybackMuting:
    """播放静音保护 —— 点歌/切歌期间的麦克风生命周期协调器（ADR-0007）。"""

    def __init__(
        self,
        mic: MicControl,
        media_session: MediaSessionPort,
        config: Optional[ConfigView] = None,
        is_guest_room: Optional[Callable[[], bool]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._mic = mic
        self._media_session = media_session
        self._config = config
        self._is_guest_room = is_guest_room or (lambda: False)
        self._logger = logger or logging.getLogger("PlaybackMuting")
        self._policy = PlaybackMutingPolicy()
        self._playback_failed = False

    @property
    def settings(self) -> PlaybackMutingSettings:
        return PlaybackMutingSettings.from_config(self._config)

    @property
    def dynamically_enabled(self) -> bool:
        return self._policy.dynamically_enabled

    def should_engage(self, settings: Optional[PlaybackMutingSettings] = None) -> bool:
        cfg = self.settings if settings is None else settings
        return self._policy.should_engage(cfg, is_guest_room=bool(self._is_guest_room()))

    def enable(self, reason: str = "") -> bool:
        changed = self._policy.enable()
        if changed:
            suffix = f": {reason}" if reason else ""
            self._logger.info(f"Playback muting enabled at runtime{suffix}")
        return changed

    def arm_on_mic(self, nickname: str) -> bool:
        settings = self.settings
        owner = RolePolicy(self._config).configured_room_owner
        name = (nickname or "").strip()
        if not settings.auto_enable_on_mic:
            return False
        if not name or not self._policy.arm_on_mic(name, settings, room_owner=owner):
            self._logger.debug(f"Playback muting not armed for on-mic user '{name}'")
            return False
        self._logger.info(f"Playback muting enabled at runtime: '{name}' 已上麦")
        return True

    def reset(self) -> None:
        if self._policy.reset():
            self._logger.info("Playback muting runtime enable reset for the new room")

    @contextmanager
    def guard(self, expected_song: Optional[str] = None) -> Iterator[bool]:
        """点歌/切歌的静音保护上下文；退出时等待播放就绪再开麦。"""
        settings = self.settings
        if not self.should_engage(settings):
            yield False
            return

        self._playback_failed = False
        muted = self._mute_if_active()
        try:
            yield muted
        except BaseException:
            self._restore_mic()
            raise

        try:
            if self._playback_failed:
                self._logger.info("Playback failed, restoring microphone immediately")
            else:
                self._wait_until_ready(settings, expected_song)
        finally:
            self._restore_mic()

    def report_failure(self) -> None:
        """静音保护期间上报播放失败，跳过就绪等待并立即恢复开麦。"""
        self._playback_failed = True

    def _mute_if_active(self) -> bool:
        if self._mic.state() is not True:
            return False
        result = self._mic.set_active(False)
        if isinstance(result, dict) and result.get("error"):
            self._logger.warning(f"Failed to mute microphone before playback: {result['error']}")
            return False
        self._logger.info("Microphone muted before playback")
        return True

    def _wait_until_ready(self, settings: PlaybackMutingSettings, expected_song: Optional[str]) -> None:
        ready = self._media_session.wait_for_playback_ready(
            expected_song=expected_song,
            timeout=settings.timeout,
            settling_delay=settings.settling_delay,
        )
        if not ready:
            self._logger.warning("Playback not ready within timeout, restoring microphone")

    def _restore_mic(self) -> None:
        try:
            result = self._mic.ensure_active()
            if isinstance(result, dict) and result.get("error"):
                self._logger.error(f"Failed to restore microphone after playback: {result['error']}")
        except Exception as exc:
            self._logger.error(f"Failed to restore microphone after playback: {exc}")


class PlaySong:
    """统一播放用例：守护 → 静音 → 驱动 UI → 房间同步与上报。"""

    def __init__(
        self,
        ui_driver: Optional[MusicUIDriverPort],
        playlist_session: PlaylistSession,
        playback_muting: PlaybackMuting,
        logger: Optional[logging.Logger] = None,
    ):
        self._ui_driver = ui_driver
        self._playlist_session = playlist_session
        self._playback_muting = playback_muting
        self._logger = logger or logging.getLogger("PlaySong")

    async def execute(self, request: PlaybackRequest) -> PlaybackResult:
        if self._ui_driver is None:
            raise RuntimeError(
                "PlaySong requires a MusicUIDriverPort adapter; "
                "construct PlaySong with ui_driver=... at the composition root."
            )

        guard_error = await self._playlist_session.guard_switch(
            request.requester, incoming_mode=request.mode.value
        )
        if guard_error:
            self._logger.info(
                f"Playback rejected by song protection: mode={request.mode.value}, "
                f"requester={request.requester}, reason={guard_error.get('error')}"
            )
            return PlaybackResult(
                status=PlaybackStatus.REJECTED,
                error=guard_error.get("error"),
            )

        with self._playback_muting.guard(expected_song=request.expected_song):
            outcome = self._ui_driver.start_playback(request)
            if not outcome.ok:
                self._playback_muting.report_failure()
                self._logger.warning(
                    f"Playback failed: mode={request.mode.value}, "
                    f"query={request.query}, error={outcome.error}"
                )
                return PlaybackResult(
                    status=PlaybackStatus.FAILED,
                    error=outcome.error,
                )

            adopt_error = self._playlist_session.adopt(
                request.requester,
                mode=request.mode.value,
                title=outcome.title or request.room_title,
                topic=outcome.topic or outcome.track.queue_line,
                playlist=outcome.playlist or request.playlist,
            )
            if adopt_error:
                self._logger.warning(
                    f"Playback started but room sync failed: "
                    f"mode={request.mode.value}, error={adopt_error.get('error')}"
                )
                return PlaybackResult(
                    status=PlaybackStatus.STARTED,
                    track=outcome.track,
                    error=adopt_error.get("error"),
                    playlist=outcome.playlist or request.playlist,
                    extra=outcome.extra,
                )

            self._logger.info(
                f"Playback started: mode={request.mode.value}, "
                f"song={outcome.track.song}, requester={request.requester}"
            )
            return PlaybackResult(
                status=PlaybackStatus.STARTED,
                track=outcome.track,
                playlist=outcome.playlist or request.playlist,
                extra=outcome.extra,
            )


class SkipSong:
    """切歌用例：先过歌单守护，再在静音保护内切到下一首。"""

    def __init__(
        self,
        media_session: MediaSessionPort,
        playlist_session: PlaylistSession,
        playback_muting: PlaybackMuting,
    ):
        self._media_session = media_session
        self._playlist_session = playlist_session
        self._playback_muting = playback_muting

    async def execute(self, requester: str) -> dict:
        guard_error = await self._playlist_session.guard_switch(requester)
        if guard_error:
            return guard_error
        with self._playback_muting.guard():
            return self._media_session.skip_song()


class PlayNext:
    """`:next` 下一首点歌用例：仅在入队成功时写入 Next Queue，不参与静音保护。"""

    def __init__(
        self,
        next_driver: NextTrackPort,
        playlist_session: PlaylistSession,
    ):
        self._next_driver = next_driver
        self._playlist_session = playlist_session

    def execute(self, requester: str, query: str) -> dict:
        info = self._next_driver.play_next(query)
        if isinstance(info, dict) and "error" not in info:
            self._playlist_session.record_next(requester)
        return info
