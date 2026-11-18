from types import SimpleNamespace
import pytest
from ushareiplay.modules.playback.broadcaster import PlaybackBroadcaster
from ushareiplay.modules.room import InfoManager, PresenceTracker, RoomStateService


@pytest.fixture
def init_singletons():
    presence = PresenceTracker()
    room_state = RoomStateService()
    room_state._logger = SimpleNamespace(info=lambda _message: None)
    return InfoManager(
        room_state=room_state,
        presence=presence,
        playback_cache=PlaybackBroadcaster(),
        logger=SimpleNamespace(info=lambda _message: None),
    )


def test_room_state_recommendation_enabled_default_and_clear(init_singletons):
    room_state = init_singletons._room_state
    assert room_state.recommendation_enabled is None

    room_state.recommendation_enabled = True
    assert room_state.recommendation_enabled is True

    room_state.recommendation_enabled = False
    assert room_state.recommendation_enabled is False

    room_state.clear()
    assert room_state.recommendation_enabled is None


def test_info_manager_recommendation_enabled_delegation(init_singletons):
    info_manager = init_singletons
    assert info_manager.recommendation_enabled is None

    info_manager._room_state.recommendation_enabled = True
    assert info_manager.recommendation_enabled is True
