from types import SimpleNamespace

import pytest

from ushareiplay.managers.playlist_session import PlaylistSession


@pytest.fixture
def playlist_session():
    PlaylistSession.reset_instance()
    state = PlaylistSession.initialize()
    state._logger = SimpleNamespace(info=lambda _msg: None)
    return state


def test_default_player_name(playlist_session):
    assert playlist_session.player_name == "Joyer"


def test_player_name_setter(playlist_session):
    playlist_session.player_name = "Alice"
    assert playlist_session.player_name == "Alice"


def test_current_playlist_name_setter(playlist_session):
    playlist_session.current_playlist_name = "My Playlist"
    assert playlist_session.current_playlist_name == "My Playlist"
