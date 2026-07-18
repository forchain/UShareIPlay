import pytest
from unittest.mock import MagicMock, patch

from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.state.online_list_scraper import OnlineListScraper
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState


@pytest.fixture
def info_manager():
    MessageDispatch.reset_instance()
    MessageDispatch.initialize()
    for cls in (
        InfoManager,
        RoomState,
        PresenceTracker,
        PlaylistState,
        PlaybackBroadcaster,
        OnlineListScraper,
    ):
        cls.reset_instance()
    RoomState.initialize()
    PresenceTracker.initialize()
    PlaylistState.initialize()
    PlaybackBroadcaster.initialize()
    OnlineListScraper.initialize()
    return InfoManager.initialize()


def _music_manager_mock():
    mock = MagicMock()
    skip_result = {"value": False}
    mock.handle_song_quality_check.side_effect = (
        lambda song_info: song_info.update({"release_date": "2020-01-02"}) or skip_result["value"]
    )
    return mock, skip_result


def test_send_playing_message_respects_broadcast_toggle(info_manager):
    mock_handler = MagicMock()
    mock_logger = MagicMock()
    info_manager._handler = mock_handler
    info_manager._logger = mock_logger

    info = {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'}
    info_manager._playback_info_cache = info

    mock_music_manager, skip_result = _music_manager_mock()
    with patch('ushareiplay.managers.music_manager.MusicManager.instance', return_value=mock_music_manager):
        # Case 1: Broadcast enabled (True) - should send message
        mock_handler.config = {'broadcast_playing_info': True}
        info_manager.send_playing_message()
        mock_handler.send_message.assert_called_once_with("SongA - SingerA • AlbumA 2020-01-02")
        mock_handler.send_message.reset_mock()
        mock_music_manager.handle_song_quality_check.assert_called_once_with(info)
        mock_music_manager.handle_song_quality_check.reset_mock()

        # Case 2: Broadcast disabled (False) - should NOT send message
        mock_handler.config = {'broadcast_playing_info': False}
        info_manager.send_playing_message()
        mock_handler.send_message.assert_not_called()
        mock_music_manager.handle_song_quality_check.assert_called_once_with(info)
        mock_music_manager.handle_song_quality_check.reset_mock()
        mock_logger.info.assert_called_with('Hidden "SongA - SingerA • AlbumA 2020-01-02"')
        mock_logger.info.reset_mock()

        # Case 3: Broadcast enabled but song skipped (quality check) - should NOT send message
        mock_handler.config = {'broadcast_playing_info': True}
        skip_result["value"] = True
        info_manager.send_playing_message()
        mock_handler.send_message.assert_not_called()

        # Case 4: Broadcast disabled (False) and song skipped (quality check)
        mock_handler.config = {'broadcast_playing_info': False}
        skip_result["value"] = True
        mock_music_manager.handle_song_quality_check.reset_mock()
        info_manager.send_playing_message()
        mock_handler.send_message.assert_not_called()
        mock_music_manager.handle_song_quality_check.assert_called_once_with(info)
        mock_logger.info.assert_not_called()


def test_send_playing_message_default_behavior(info_manager):
    mock_handler = MagicMock()
    info_manager._handler = mock_handler
    info_manager._logger = MagicMock()

    info = {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'}
    info_manager._playback_info_cache = info

    mock_music_manager = MagicMock()
    mock_music_manager.handle_song_quality_check.side_effect = (
        lambda song_info: song_info.update({"release_date": "2020-01-02"}) or False
    )

    with patch('ushareiplay.managers.music_manager.MusicManager.instance', return_value=mock_music_manager):
        mock_handler.config = {}
        info_manager.send_playing_message()
        mock_handler.send_message.assert_called_once_with("SongA - SingerA • AlbumA 2020-01-02")


def test_send_playing_message_backward_compatible_nested_config(info_manager):
    mock_handler = MagicMock()
    info_manager._handler = mock_handler
    info_manager._logger = MagicMock()
    info_manager._playback_info_cache = {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'}

    mock_music_manager = MagicMock()
    mock_music_manager.handle_song_quality_check.return_value = False

    with patch('ushareiplay.managers.music_manager.MusicManager.instance', return_value=mock_music_manager):
        mock_handler.config = {'soul': {'broadcast_playing_info': False}}
        info_manager.send_playing_message()
        mock_handler.send_message.assert_not_called()


def test_ensure_cached_release_date_updates_playback_cache(info_manager):
    info_manager._playback_info_cache = {
        "song": "如风",
        "singer": "王菲",
        "album": "十万个为什么？(日本版）",
    }

    mock_music_manager = MagicMock()
    mock_music_manager.ensure_release_date.side_effect = (
        lambda song_info: song_info.update({"release_date": "1993-09-07"})
    )

    with patch('ushareiplay.managers.music_manager.MusicManager.instance', return_value=mock_music_manager):
        result = info_manager.ensure_cached_release_date()

    assert result["release_date"] == "1993-09-07"
    assert info_manager.get_playback_info_cache()["release_date"] == "1993-09-07"
