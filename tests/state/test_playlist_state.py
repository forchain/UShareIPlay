from types import SimpleNamespace

import pytest

from ushareiplay.modules.playback.use_cases import PlaylistSession


@pytest.fixture
def playlist_session():
    return PlaylistSession(logger=SimpleNamespace(info=lambda _msg: None))


def test_default_player_name(playlist_session):
    assert playlist_session.player_name == "Joyer"


def test_player_name_setter(playlist_session):
    playlist_session.player_name = "Alice"
    assert playlist_session.player_name == "Alice"


def test_current_playlist_name_setter(playlist_session):
    playlist_session.current_playlist_name = "My Playlist"
    assert playlist_session.current_playlist_name == "My Playlist"
