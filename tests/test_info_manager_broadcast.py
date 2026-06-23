import pytest
from unittest.mock import MagicMock, patch
from ushareiplay.managers.info_manager import InfoManager

@pytest.fixture
def info_manager():
    # Reset InfoManager singleton
    if hasattr(InfoManager, '_instance'):
        del InfoManager._instance
    return InfoManager.instance()

def test_send_playing_message_respects_broadcast_toggle(info_manager):
    # Mock handler and logger
    mock_handler = MagicMock()
    mock_logger = MagicMock()
    info_manager._handler = mock_handler
    info_manager._logger = mock_logger
    
    # Setup playback info cache
    info = {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'}
    info_manager._playback_info_cache = info
    
    with patch('ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance') as mock_qq_instance:
        mock_music_handler = MagicMock()
        mock_qq_instance.return_value = mock_music_handler
        skip_result = {"value": False}
        mock_music_handler.handle_song_quality_check.side_effect = (
            lambda song_info: song_info.update({"release_date": "2020-01-02"}) or skip_result["value"]
        )
        
        # Case 1: Broadcast enabled (True) - should send message
        mock_handler.config = {'broadcast_playing_info': True}
        info_manager.send_playing_message()
        mock_handler.send_message.assert_called_once_with("SongA - SingerA • AlbumA 2020-01-02")
        mock_handler.send_message.reset_mock()
        mock_music_handler.handle_song_quality_check.assert_called_once_with(info)
        mock_music_handler.handle_song_quality_check.reset_mock()
        
        # Case 2: Broadcast disabled (False) - should NOT send message
        mock_handler.config = {'broadcast_playing_info': False}
        info_manager.send_playing_message()
        mock_handler.send_message.assert_not_called()
        mock_music_handler.handle_song_quality_check.assert_called_once_with(info)
        mock_music_handler.handle_song_quality_check.reset_mock()
        mock_logger.info.assert_called_with('Hidden "SongA - SingerA • AlbumA 2020-01-02"')
        mock_logger.info.reset_mock()
        
        # Case 3: Broadcast enabled but song skipped (quality check) - should NOT send message
        mock_handler.config = {'broadcast_playing_info': True}
        skip_result["value"] = True
        info_manager.send_playing_message()
        mock_handler.send_message.assert_not_called()

        # Case 4: Broadcast disabled (False) and song skipped (quality check) - should NOT send message and should NOT log broadcast disabled message
        mock_handler.config = {'broadcast_playing_info': False}
        skip_result["value"] = True
        mock_music_handler.handle_song_quality_check.reset_mock()
        info_manager.send_playing_message()
        mock_handler.send_message.assert_not_called()
        mock_music_handler.handle_song_quality_check.assert_called_once_with(info)
        mock_logger.info.assert_not_called()

def test_send_playing_message_default_behavior(info_manager):
    # Mock handler
    mock_handler = MagicMock()
    info_manager._handler = mock_handler
    info_manager._logger = MagicMock()
    
    # Setup playback info cache
    info = {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'}
    info_manager._playback_info_cache = info
    
    with patch('ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance') as mock_qq_instance:
        mock_music_handler = MagicMock()
        mock_qq_instance.return_value = mock_music_handler
        mock_music_handler.handle_song_quality_check.return_value = False
        mock_music_handler.handle_song_quality_check.side_effect = (
            lambda song_info: song_info.update({"release_date": "2020-01-02"}) or False
        )
        
        # Case: Config missing 'broadcast_playing_info' - should default to True and send message
        mock_handler.config = {}
        info_manager.send_playing_message()
        mock_handler.send_message.assert_called_once_with("SongA - SingerA • AlbumA 2020-01-02")


def test_send_playing_message_backward_compatible_nested_config(info_manager):
    mock_handler = MagicMock()
    info_manager._handler = mock_handler
    info_manager._logger = MagicMock()
    info_manager._playback_info_cache = {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'}

    with patch('ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance') as mock_qq_instance:
        mock_music_handler = MagicMock()
        mock_qq_instance.return_value = mock_music_handler
        mock_music_handler.handle_song_quality_check.return_value = False

        # Backward-compatible path: nested full config shape
        mock_handler.config = {'soul': {'broadcast_playing_info': False}}
        info_manager.send_playing_message()
        mock_handler.send_message.assert_not_called()


def test_ensure_cached_release_date_updates_playback_cache(info_manager):
    info_manager._playback_info_cache = {
        "song": "如风",
        "singer": "王菲",
        "album": "十万个为什么？(日本版）",
    }

    with patch("ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance") as mock_qq_instance:
        mock_music_handler = MagicMock()
        mock_qq_instance.return_value = mock_music_handler
        mock_music_handler.ensure_release_date.side_effect = (
            lambda song_info: song_info.update({"release_date": "1993-09-07"})
        )

        result = info_manager.ensure_cached_release_date()

    assert result["release_date"] == "1993-09-07"
    assert info_manager.get_playback_info_cache()["release_date"] == "1993-09-07"
