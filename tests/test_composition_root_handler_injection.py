"""验证 Composition Root 注入 handler 时，服务持有的 handler 与注入对象是同一个实例（身份相等）。"""
from unittest.mock import MagicMock
import pytest
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.managers.admin_manager import AdminManager
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.event_manager import EventManager
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.keyword_manager import KeywordManager
from ushareiplay.managers.message_manager import MessageManager
from ushareiplay.managers.mic_manager import MicManager
from ushareiplay.managers.notice_manager import NoticeManager
from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.managers.recommendation_manager import RecommendationManager
from ushareiplay.managers.recovery_manager import RecoveryManager
from ushareiplay.managers.room_info_window import RoomInfoWindow
from ushareiplay.managers.room_name_manager import RoomNameManager
from ushareiplay.managers.timer_manager import TimerManager
from ushareiplay.managers.topic_manager import TopicManager
from ushareiplay.managers.user_manager import UserManager
from ushareiplay.state.online_list_scraper import OnlineListScraper
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def reset_all_test_singletons():
    Singleton.reset_all_instances()
    yield
    Singleton.reset_all_instances()


def test_composition_root_services_receive_identical_injected_handler():
    fake_soul_handler = MagicMock(name="FakeSoulHandler")

    services = [
        UserManager.initialize(fake_soul_handler),
        MessageManager.initialize(fake_soul_handler),
        MessageDispatch.initialize(fake_soul_handler),
        TopicManager.initialize(fake_soul_handler),
        TimerManager.initialize(fake_soul_handler),
        CommandManager.initialize(fake_soul_handler),
        RoomState.initialize(fake_soul_handler),
        PresenceTracker.initialize(fake_soul_handler),
        PlaylistState.initialize(fake_soul_handler),
        PlaybackBroadcaster.initialize(fake_soul_handler),
        OnlineListScraper.initialize(fake_soul_handler),
        InfoManager.initialize(fake_soul_handler),
        PartyManager.initialize(fake_soul_handler),
        NoticeManager.initialize(fake_soul_handler),
        RecommendationManager.initialize(fake_soul_handler),
        RoomNameManager.initialize(fake_soul_handler),
        RoomInfoWindow.initialize(fake_soul_handler),
        AdminManager.initialize(fake_soul_handler),
        KeywordManager.initialize(fake_soul_handler),
        EventManager.initialize(fake_soul_handler),
        RecoveryManager.initialize(fake_soul_handler),
        MicManager.initialize(fake_soul_handler),
        PlaybackMuting.initialize(fake_soul_handler),
    ]

    for service in services:
        h = getattr(service, "handler", None) or getattr(service, "soul_handler", None)
        assert h is fake_soul_handler, (
            f"{service.__class__.__name__}.handler ({h}) is not "
            f"identically equal to injected fake_soul_handler ({fake_soul_handler})"
        )


def test_services_fallback_to_lazy_handler_when_not_injected():
    room_state = RoomState.initialize()
    assert room_state._handler is None
    assert room_state.handler is None
