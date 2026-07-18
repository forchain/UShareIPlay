from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster


@pytest.fixture
def broadcaster():
    if hasattr(PlaybackBroadcaster, "_instance"):
        del PlaybackBroadcaster._instance
    b = PlaybackBroadcaster.instance()
    b._logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    b._soul_handler = MagicMock()
    b._music_handler = MagicMock()
    return b


def test_update_playback_info_cache_sets_cache(broadcaster):
    broadcaster._music_handler.get_playback_info.return_value = {
        "song": "SongA",
        "singer": "SingerA",
        "album": "AlbumA",
        "state": "playing",
    }
    broadcaster.update_playback_info_cache()

    cache = broadcaster.get_playback_info_cache()
    assert cache["song"] == "SongA"
    assert cache["state"] is None


def test_update_playback_info_cache_falls_back_on_error(broadcaster):
    broadcaster._music_handler.get_playback_info.side_effect = RuntimeError("boom")
    broadcaster.update_playback_info_cache()

    cache = broadcaster.get_playback_info_cache()
    assert "error" in cache
    assert cache["song"] == "Unknown"


def test_send_playing_message_respects_broadcast_toggle(broadcaster):
    info = {"song": "SongA", "singer": "SingerA", "album": "AlbumA"}
    broadcaster._playback_info_cache = info
    broadcaster._music_handler.handle_song_quality_check.return_value = False

    broadcaster._soul_handler.config = {"broadcast_playing_info": True}
    broadcaster.send_playing_message()
    broadcaster._soul_handler.send_message.assert_called_once_with(
        "SongA - SingerA • AlbumA"
    )

    broadcaster._soul_handler.send_message.reset_mock()
    broadcaster._soul_handler.config = {"broadcast_playing_info": False}
    broadcaster.send_playing_message()
    broadcaster._soul_handler.send_message.assert_not_called()


def test_send_playing_message_skips_when_song_quality_check_skips(broadcaster):
    info = {"song": "SongA", "singer": "SingerA", "album": "AlbumA"}
    broadcaster._playback_info_cache = info
    broadcaster._music_handler.handle_song_quality_check.return_value = True

    broadcaster._soul_handler.config = {"broadcast_playing_info": True}
    broadcaster.send_playing_message()
    broadcaster._soul_handler.send_message.assert_not_called()


def test_ensure_cached_release_date_fetches_when_missing(broadcaster):
    info = {"song": "SongA", "singer": "SingerA", "album": "AlbumA"}
    broadcaster._playback_info_cache = info
    broadcaster._music_handler.ensure_release_date.side_effect = (
        lambda song_info: song_info.update({"release_date": "2020-01-02"})
    )

    result = broadcaster.ensure_cached_release_date()

    assert result["release_date"] == "2020-01-02"


def test_update_detects_song_change_and_broadcasts(broadcaster):
    broadcaster._playback_info_cache = {
        "song": "SongA",
        "singer": "SingerA",
        "album": "AlbumA",
    }
    broadcaster._music_handler.handle_song_quality_check.return_value = False
    broadcaster._soul_handler.config = {"broadcast_playing_info": True}

    # First update establishes baseline
    broadcaster.update()
    broadcaster._soul_handler.send_message.assert_not_called()

    # Change song and update again
    broadcaster._playback_info_cache = {
        "song": "SongB",
        "singer": "SingerB",
        "album": "AlbumB",
    }
    broadcaster.update()
    broadcaster._soul_handler.send_message.assert_called_once()
