"""Timer `;` batches under Playlist Guard: skip only the interrupting parts.

A timer emits one queue-grammar message whose `;`-separated parts are executed
in order. Guard checks live inside the commands/engine (radio/play/playlist go
through `MusicManager.play()`, skip/pause ask `guard_switch` themselves), so a
guarded batch must still run `:say` / `:title` / `:topic` / `:vol` / `:next`
while only the playback-interrupting parts are rejected.

The seam is the production one: `CommandManager.execute_runtime_queue_messages`
with real command classes and the real `InfoManager` / `PlaylistSession`
guard. Only the UI edges are replaced (in-memory music driver, fake controller
handlers).
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ushareiplay.adapters.outbound.system.config_loader import ConfigLoader
from ushareiplay.modules.shared.config import ConfigSectionView
from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
from ushareiplay.modules.room import InfoManager
from ushareiplay.adapters.outbound.appium.qq_music.music_manager import MusicManager
from ushareiplay.modules.playback.use_cases import PlaybackMuting, PlaylistSession
from ushareiplay.modules.shared.message_info import MessageInfo
from ushareiplay.modules.playback.broadcaster import PlaybackBroadcaster
from ushareiplay.modules.room.use_cases import PresenceTracker, RoomStateService
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger("test_timer_batch_guard")


@pytest.fixture
def clean_info_manager():
    from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository

    fake_logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    room_state = RoomStateService()
    room_state._logger = fake_logger
    presence = PresenceTracker()
    presence._logger = fake_logger
    playlist = PlaylistSession(
        online_users=presence.get_online_users,
        avatar_usernames=TortoiseUserRepository().get_all_avatar_usernames,
        logger=fake_logger,
    )
    broadcaster = PlaybackBroadcaster(playlist_session=playlist)
    broadcaster._logger = fake_logger
    return InfoManager(
        room_state=room_state,
        presence=presence,
        playlist=playlist,
        playback_cache=broadcaster,
        logger=fake_logger,
    )


class _RecordingDispatch:
    """Command outputs and screen messages, without a real chat drawer."""

    def __init__(self):
        self.outputs = []
        self.screen_messages = []

    def bind_handler(self, _handler):
        return self

    def configure_runtime(self, _runtime):
        pass

    def send_screen_message(self, message, silent=False):
        self.screen_messages.append(message)

    async def send_for_message_info(self, message_info, response, silent=False):
        self.outputs.append(response)
        return True


class _Runtime:
    def __init__(self, controller):
        self.controller = controller

    def emit(self, name, **kwargs):
        pass

    @asynccontextmanager
    async def ui_session(self, reason):
        yield


class _AppiumStub:
    """Only the `mobile: shell` reads volume/skip/pause touch."""

    def __init__(self):
        self.commands = []

    def execute_script(self, script, payload=None):
        command = (payload or {}).get("command", "")
        self.commands.append(command)
        if command == "dumpsys audio":
            return "- STREAM_MUSIC:\n  streamVolume:3"
        return None


class _RoomProfileStub:
    def __init__(self):
        self.titles = []
        self.topics = []

    def set_title(self, title, theme=None):
        self.titles.append(title)
        return {"title": title}

    def set_topic(self, topic):
        self.topics.append(topic)
        return {"topic": topic}


class _Mic:
    def __init__(self):
        self.calls = []

    def set_active(self, enable):
        self.calls.append(enable)
        return {}

    def state(self):
        return False

    def ensure_active(self):
        return {}


class _Seam:
    def __init__(self, manager, driver, room, appium, pause_mic, info):
        self.manager = manager
        self.driver = driver
        self.room = room
        self.appium = appium
        self.pause_mic = pause_mic
        self.info = info

    def run(self, content):
        message = MessageInfo(
            content=content,
            nickname="Timer",
            source="timer",
            sleep_exempt=True,
        )
        return asyncio.run(
            self.manager.execute_runtime_queue_messages([message])
        ), self.manager.message_dispatch


@pytest.fixture
def batch_seam(clean_info_manager, monkeypatch):
    config = ConfigLoader.load_config()
    driver = InMemoryMusicUIDriver()

    # 守护现在会让 Next Queue 的 avatar 查询失败即暴露；本 seam 不接 DB，
    # 因此把这一条数据边界替换成「每个名字就是自己的唯一分身」。
    async def _avatars(username):
        return {username}

    music_handler = SimpleNamespace(
        logger=LOGGER,
        play_next=lambda query: {
            "song": query,
            "singer": "歌手",
            "album": "",
            "release_date": "",
        },
        key_actions=SimpleNamespace(
            press_volume_up=lambda: None, press_volume_down=lambda: None
        ),
    )
    controller = SimpleNamespace(
        soul_handler=SimpleNamespace(logger=LOGGER),
        music_handler=music_handler,
        config=config,
        obs=SimpleNamespace(emit=lambda *args, **kwargs: None),
    )

    from ushareiplay.adapters.outbound.system.clock import SystemClock

    dispatch = _RecordingDispatch()
    manager = CommandManager(message_dispatch=dispatch, clock=SystemClock())
    manager.configure_runtime(_Runtime(controller))
    manager._logger = LOGGER
    manager._handler = SimpleNamespace(config=config, logger=LOGGER)
    manager.initialize_parser(config)

    # Only the room-facing edges are stubs; guard decisions stay real.
    room = _RoomProfileStub()
    manager.get_command("title")._room_profile_manager = room
    manager.get_command("topic")._room_profile_manager = room
    pause_mic = _Mic()

    music = MusicManager(
        music_handler=music_handler,
        playlist_session=clean_info_manager._playlist,
        config=config,
    )
    appium = _AppiumStub()
    music.driver = appium
    music_handler.driver = appium

    from ushareiplay.adapters.outbound.appium.qq_music.media_session import (
        QQMusicMediaSession,
    )
    from ushareiplay.modules.playback.use_cases import (
        AdjustVolume,
        PauseResume,
        PlayNext,
        PlaySong,
        SkipSong,
    )

    session = clean_info_manager._playlist
    session._room_profile = room
    session._config = config
    session._avatar_usernames = _avatars

    muting = PlaybackMuting(
        mic=SimpleNamespace(state=lambda: False, set_active=lambda *_a: {}, ensure_active=lambda: {}),
        media_session=SimpleNamespace(wait_for_playback_ready=lambda **_kw: True),
        config=ConfigSectionView("soul", {}),
        logger=LOGGER,
    )
    controller.playlist_session = session
    controller.play_song = PlaySong(
        ui_driver=driver,
        playlist_session=session,
        playback_muting=muting,
        logger=LOGGER,
    )
    controller.skip_song = SkipSong(
        media_session=music,
        playlist_session=session,
        playback_muting=muting,
    )
    controller.play_next = PlayNext(
        next_driver=music_handler,
        playlist_session=session,
    )
    media_session_adapter = QQMusicMediaSession(music_handler)
    controller.pause_resume = PauseResume(
        media_session=music,
        playback_control=media_session_adapter,
        playlist_session=session,
        mic=pause_mic,
        logger=LOGGER,
    )
    controller.adjust_volume = AdjustVolume(
        playback_control=media_session_adapter,
        logger=LOGGER,
    )

    return _Seam(manager, driver, room, appium, pause_mic, clean_info_manager)


def test_guarded_batch_runs_non_interrupting_parts_and_drops_radio(batch_seam):
    """Playlist Context owner online: say/title/topic/vol run, radio never does."""
    batch_seam.info._playlist.player_name = "Alice"
    batch_seam.info._presence.update_online_users(["Alice", "Joyer"])

    routed, dispatch = batch_seam.run(
        ":say 晚安;:title 晚安;:topic 晚安;:vol 5;:radio sleep"
    )

    assert routed == 5
    assert dispatch.outputs[0] == "晚安 @Timer"
    assert batch_seam.room.titles == ["晚安"]
    assert batch_seam.room.topics == ["晚安"]
    assert "Adjusted volume" in dispatch.outputs[3]
    assert "Alice 正在播放歌单" in dispatch.outputs[4]
    assert batch_seam.driver.requests == []


def test_guarded_batch_still_records_next_but_blocks_radio(batch_seam):
    """A guest's pending Next Queue guards the timer; its `:next` still records."""
    batch_seam.info._playlist.record_next("Alice")
    batch_seam.info._presence.update_online_users(["Alice", "Joyer"])

    routed, dispatch = batch_seam.run(":say 晚安;:next 晴天;:radio sleep")

    assert routed == 3
    assert dispatch.outputs[0] == "晚安 @Timer"
    assert "晴天" in dispatch.outputs[1] and "Failed" not in dispatch.outputs[1]
    assert "Alice 正在点歌" in dispatch.outputs[2]

    assert batch_seam.info.pending_next_count == 2
    assert batch_seam.info.next_queue_contributors == {"Alice", "Timer"}
    assert batch_seam.driver.requests == []


def test_unguarded_batch_runs_the_interrupting_commands(batch_seam):
    """No active guard: radio and single-song play both reach the driver."""
    routed, dispatch = batch_seam.run(":say 晚安;:radio sleep;:play 晴天")

    assert routed == 3
    assert "Failed" not in "".join(dispatch.outputs)
    assert [request.mode.value for request in batch_seam.driver.requests] == [
        "radio",
        "song",
    ]


def test_guarded_batch_blocks_single_song_play_and_playlist(batch_seam):
    """Timer's `:play` is automated interruption, so single-song exemption doesn't apply.

    `:playlist <query>` is a continuous-queue switch and is guarded like radio.
    """
    batch_seam.info._playlist.player_name = "Alice"
    batch_seam.info._presence.update_online_users(["Alice", "Joyer"])

    routed, dispatch = batch_seam.run(":play 晴天;:playlist 晚安歌单")

    assert routed == 2
    assert all("Alice 正在播放歌单" in response for response in dispatch.outputs)
    assert batch_seam.driver.requests == []


def test_guarded_batch_blocks_skip_and_pause_without_touching_playback(batch_seam):
    """Skip/pause in a guarded batch never reach the player or the microphone."""
    batch_seam.info._playlist.player_name = "Alice"
    batch_seam.info._presence.update_online_users(["Alice", "Joyer"])

    routed, dispatch = batch_seam.run(":skip;:pause")

    assert routed == 2
    assert all("Alice 正在播放歌单" in response for response in dispatch.outputs)
    assert not any("KEYCODE_MEDIA_NEXT" in c for c in batch_seam.appium.commands)
    assert not any("KEYCODE_MEDIA_PLAY_PAUSE" in c for c in batch_seam.appium.commands)
    assert batch_seam.pause_mic.calls == []
