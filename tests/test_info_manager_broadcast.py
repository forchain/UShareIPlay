import pytest
from unittest.mock import MagicMock

from ushareiplay.adapters.outbound.appium.soul.message_dispatch import MessageDispatch
from ushareiplay.modules.room import InfoManager, PresenceTracker, RoomStateService
from ushareiplay.modules.playback.broadcaster import PlaybackBroadcaster
from ushareiplay.modules.playback.use_cases import PlaylistSession
from ushareiplay.modules.shared.config import ConfigSectionView


@pytest.fixture
def info_manager():
    room_state = RoomStateService()
    presence = PresenceTracker()
    playlist = PlaylistSession()
    broadcaster = PlaybackBroadcaster(playlist_session=playlist)
    return InfoManager(
        room_state=room_state,
        presence=presence,
        playlist=playlist,
        playback_cache=broadcaster,
    )


def _music_manager_mock():
    mock = MagicMock()
    skip_result = {"value": False}
    mock.handle_song_quality_check.side_effect = (
        lambda song_info: song_info.update({"release_date": "2020-01-02"}) or skip_result["value"]
    )
    return mock, skip_result


def _inject_broadcaster(info_manager, mock_handler, mock_logger, cache, music_manager=None):
    """直接向 PlaybackBroadcaster 注入测试替身（见 ADR-0004）。"""
    broadcaster = info_manager._playback_cache
    broadcaster._soul_handler = mock_handler
    broadcaster._message_dispatch = MessageDispatch(handler=mock_handler)
    broadcaster._logger = mock_logger
    broadcaster._playback_info_cache = cache
    if music_manager is not None:
        broadcaster._music_manager = music_manager
    return broadcaster


def test_send_playing_message_respects_broadcast_toggle(info_manager):
    mock_handler = MagicMock()
    mock_logger = MagicMock()

    info = {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'}
    mock_music_manager, skip_result = _music_manager_mock()
    broadcaster = _inject_broadcaster(
        info_manager, mock_handler, mock_logger, info, music_manager=mock_music_manager
    )

    # Case 1: Broadcast enabled (True) - should send message
    mock_handler.config = ConfigSectionView('soul', {'broadcast_playing_info': True})
    broadcaster.send_playing_message()
    mock_handler.send_message.assert_called_once_with("SongA - SingerA • AlbumA 2020-01-02")
    mock_handler.send_message.reset_mock()
    mock_music_manager.handle_song_quality_check.assert_called_once_with(info)
    mock_music_manager.handle_song_quality_check.reset_mock()

    # Case 2: Broadcast disabled (False) - should NOT send message
    mock_handler.config = ConfigSectionView('soul', {'broadcast_playing_info': False})
    broadcaster.send_playing_message()
    mock_handler.send_message.assert_not_called()
    mock_music_manager.handle_song_quality_check.assert_called_once_with(info)
    mock_music_manager.handle_song_quality_check.reset_mock()
    mock_logger.info.assert_called_with('Hidden "SongA - SingerA • AlbumA 2020-01-02"')
    mock_logger.info.reset_mock()

    # Case 3: Broadcast enabled but song skipped (quality check) - should NOT send message
    mock_handler.config = ConfigSectionView('soul', {'broadcast_playing_info': True})
    skip_result["value"] = True
    broadcaster.send_playing_message()
    mock_handler.send_message.assert_not_called()

    # Case 4: Broadcast disabled (False) and song skipped (quality check)
    mock_handler.config = ConfigSectionView('soul', {'broadcast_playing_info': False})
    skip_result["value"] = True
    mock_music_manager.handle_song_quality_check.reset_mock()
    broadcaster.send_playing_message()
    mock_handler.send_message.assert_not_called()
    mock_music_manager.handle_song_quality_check.assert_called_once_with(info)
    mock_logger.info.assert_not_called()


def test_send_playing_message_default_behavior(info_manager):
    mock_handler = MagicMock()

    info = {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'}
    mock_music_manager = MagicMock()
    mock_music_manager.handle_song_quality_check.side_effect = (
        lambda song_info: song_info.update({"release_date": "2020-01-02"}) or False
    )
    broadcaster = _inject_broadcaster(
        info_manager, mock_handler, MagicMock(), info, music_manager=mock_music_manager
    )

    mock_handler.config = ConfigSectionView('soul', {})
    broadcaster.send_playing_message()
    mock_handler.send_message.assert_called_once_with("SongA - SingerA • AlbumA 2020-01-02")


def test_send_playing_message_reads_the_switch_from_the_soul_section(info_manager):
    """开关就在 soul 段里：没有「根配置里再套一层 soul」的形状试探了。"""
    mock_handler = MagicMock()
    mock_music_manager = MagicMock()
    mock_music_manager.handle_song_quality_check.return_value = False
    broadcaster = _inject_broadcaster(
        info_manager,
        mock_handler,
        MagicMock(),
        {'song': 'SongA', 'singer': 'SingerA', 'album': 'AlbumA'},
        music_manager=mock_music_manager,
    )

    mock_handler.config = ConfigSectionView('soul', {'broadcast_playing_info': False})
    broadcaster.send_playing_message()
    mock_handler.send_message.assert_not_called()


def test_ensure_cached_release_date_updates_playback_cache(info_manager):
    broadcaster = info_manager._playback_cache
    broadcaster._playback_info_cache = {
        "song": "如风",
        "singer": "王菲",
        "album": "十万个为什么？(日本版）",
    }

    mock_music_manager = MagicMock()
    mock_music_manager.ensure_release_date.side_effect = (
        lambda song_info: song_info.update({"release_date": "1993-09-07"})
    )
    broadcaster._music_manager = mock_music_manager

    result = info_manager.ensure_cached_release_date()

    assert result["release_date"] == "1993-09-07"
    assert info_manager.get_playback_info_cache()["release_date"] == "1993-09-07"
