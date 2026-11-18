from types import SimpleNamespace
import pytest
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.managers.playlist_session import PlaylistSession
from tests.legacy_state import PresenceTracker
from tests.legacy_state import RoomState
from ushareiplay.modules.room import InfoManager


@pytest.fixture
def init_singletons():
    for cls in (
        PlaybackBroadcaster,
        PlaylistSession,
        PresenceTracker,
        RoomState,
    ):
        cls.reset_instance()
    PlaybackBroadcaster.initialize()
    PlaylistSession.initialize()
    presence = PresenceTracker.initialize()
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _message: None)
    return InfoManager(
        room_state=room_state,
        presence=presence,
        logger=SimpleNamespace(info=lambda _message: None),
    )


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
    info_manager = init_singletons
    assert info_manager.recommendation_enabled is None

    RoomState.instance().recommendation_enabled = True
    assert info_manager.recommendation_enabled is True
