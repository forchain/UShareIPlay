from types import SimpleNamespace

import pytest

from ushareiplay.modules.room import InfoManager, PresenceTracker
from ushareiplay.managers.playlist_session import PlaylistSession
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from tests.room_support import configured_room_state


@pytest.fixture
def info_manager():
    for cls in (PlaylistSession, PlaybackBroadcaster):
        cls.reset_instance()
    fake_logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    room_state = configured_room_state(logger=fake_logger)
    presence = PresenceTracker(logger=fake_logger)
    playlist = PlaylistSession.initialize()
    broadcaster = PlaybackBroadcaster.initialize()
    broadcaster._logger = fake_logger
    return InfoManager(
        room_state=room_state,
        presence=presence,
        playlist=playlist,
        playback_cache=broadcaster,
        logger=fake_logger,
    )


def test_facade_delegates_user_count(info_manager):
    info_manager._room_state.user_count = 10
    assert info_manager.user_count == 10


def test_facade_delegates_focus_count(info_manager):
    info_manager._room_state.focus_count = 5
    assert info_manager.focus_count == 5


def test_facade_delegates_room_id(info_manager):
    info_manager._room_state.room_id = "FM123"
    assert info_manager.room_id == "FM123"


def test_facade_reads_player_name_from_the_session(info_manager):
    info_manager._playlist.player_name = "Alice"
    assert info_manager.player_name == "Alice"


def test_facade_reads_current_playlist_name_from_the_session(info_manager):
    info_manager._playlist.current_playlist_name = "My Playlist"
    assert info_manager.current_playlist_name == "My Playlist"


def test_facade_delegates_online_users(info_manager):
    info_manager._presence.update_online_users(["alice", "bob"])
    assert info_manager.is_user_online("alice") is True
    assert info_manager.get_online_users() == {"alice", "bob"}


def test_facade_delegates_playback_info_cache(info_manager):
    cache = {"song": "SongA", "singer": "SingerA", "album": "AlbumA"}
    PlaybackBroadcaster.instance()._playback_info_cache = cache
    assert info_manager.get_playback_info_cache() is cache


def test_facade_reflects_cleared_state(info_manager):
    info_manager._room_state.user_count = 10
    info_manager._room_state.focus_count = 5
    info_manager._room_state.room_id = "FM123"
    info_manager._presence.update_online_users(["alice"])

    info_manager._room_state.clear()
    info_manager._presence.clear()

    assert info_manager.user_count is None
    assert info_manager.focus_count is None
    assert info_manager.room_id is None
    assert info_manager.get_online_users() == set()
