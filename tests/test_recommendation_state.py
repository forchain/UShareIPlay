from types import SimpleNamespace
import pytest
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState
from ushareiplay.managers.info_manager import InfoManager


@pytest.fixture
def init_singletons():
    for cls in (
        InfoManager,
        PlaybackBroadcaster,
        PlaylistState,
        PresenceTracker,
        RoomState,
    ):
        cls.reset_instance()
    PlaybackBroadcaster.initialize()
    PlaylistState.initialize()
    PresenceTracker.initialize()
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _message: None)
    manager = InfoManager.initialize()
    manager._logger = SimpleNamespace(info=lambda _message: None)
    return manager


def test_room_state_recommendation_enabled_default_and_clear(init_singletons):
    room_state = RoomState.instance()
    assert room_state.recommendation_enabled is None

    room_state.recommendation_enabled = True
    assert room_state.recommendation_enabled is True

    room_state.recommendation_enabled = False
    assert room_state.recommendation_enabled is False

    room_state.clear()
    assert room_state.recommendation_enabled is None


def test_info_manager_recommendation_enabled_delegation(init_singletons):
    info_manager = InfoManager.instance()
    assert info_manager.recommendation_enabled is None

    info_manager.recommendation_enabled = True
    assert info_manager.recommendation_enabled is True
    assert RoomState.instance().recommendation_enabled is True
