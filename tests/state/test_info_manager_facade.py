from types import SimpleNamespace

import pytest

from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.state.online_list_scraper import OnlineListScraper
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState


@pytest.fixture
def info_manager():
    for cls in (
        InfoManager,
        RoomState,
        PresenceTracker,
        PlaylistState,
        PlaybackBroadcaster,
        OnlineListScraper,
    ):
        if hasattr(cls, "_instance"):
            del cls._instance
    manager = InfoManager.instance()
    manager._logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    return manager


def test_facade_delegates_user_count(info_manager):
    info_manager.user_count = 10
    assert info_manager.user_count == 10
    assert info_manager._room_state.user_count == 10


def test_facade_delegates_focus_count(info_manager):
    info_manager.focus_count = 5
    assert info_manager.focus_count == 5
    assert info_manager._room_state.focus_count == 5


def test_facade_delegates_room_id(info_manager):
    info_manager.room_id = "FM123"
    assert info_manager.room_id == "FM123"
    assert info_manager._room_state.room_id == "FM123"


def test_facade_delegates_player_name(info_manager):
    info_manager.player_name = "Alice"
    assert info_manager.player_name == "Alice"
    assert info_manager._playlist_state.player_name == "Alice"


def test_facade_delegates_current_playlist_name(info_manager):
    info_manager.current_playlist_name = "My Playlist"
    assert info_manager.current_playlist_name == "My Playlist"
    assert info_manager._playlist_state.current_playlist_name == "My Playlist"


def test_facade_delegates_online_users(info_manager):
    info_manager.update_online_users(["alice", "bob"])
    assert info_manager.is_user_online("alice") is True
    assert info_manager.get_online_users() == {"alice", "bob"}
    assert info_manager._presence_tracker.get_online_users() == {"alice", "bob"}


def test_facade_delegates_playback_info_cache(info_manager):
    cache = {"song": "SongA", "singer": "SingerA", "album": "AlbumA"}
    info_manager._playback_info_cache = cache
    assert info_manager.get_playback_info_cache() is cache
    assert info_manager._playback_broadcaster.get_playback_info_cache() is cache


def test_facade_clear_resets_state(info_manager):
    info_manager.user_count = 10
    info_manager.focus_count = 5
    info_manager.room_id = "FM123"
    info_manager.update_online_users(["alice"])

    info_manager.clear()

    assert info_manager.user_count is None
    assert info_manager.focus_count is None
    assert info_manager.room_id is None
    assert info_manager.get_online_users() == set()
