from types import SimpleNamespace

import pytest

from ushareiplay.state.playlist_state import PlaylistState


@pytest.fixture
def playlist_state():
    PlaylistState.reset_instance()
    state = PlaylistState.initialize()
    state._logger = SimpleNamespace(info=lambda _msg: None)
    return state


def test_default_player_name(playlist_state):
    assert playlist_state.player_name == "Joyer"


def test_player_name_setter(playlist_state):
    playlist_state.player_name = "Alice"
    assert playlist_state.player_name == "Alice"


def test_current_playlist_name_setter(playlist_state):
    playlist_state.current_playlist_name = "My Playlist"
    assert playlist_state.current_playlist_name == "My Playlist"
