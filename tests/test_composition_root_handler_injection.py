"""验证 Composition Root 注入 handler 时，服务持有的 handler 与注入对象是同一个实例（身份相等）。"""
from unittest.mock import MagicMock
import pytest
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
from ushareiplay.adapters.inbound.ui_events.event_manager import EventManager
from ushareiplay.adapters.inbound.runtime.message_manager import MessageManager
from ushareiplay.managers.recovery_manager import RecoveryManager
from tests.room_profile_support import RoomProfileManager
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster


@pytest.fixture(autouse=True)
def reset_all_test_singletons():
    Singleton.reset_all_instances()
    yield
    Singleton.reset_all_instances()


def test_composition_root_services_receive_identical_injected_handler():
    fake_soul_handler = MagicMock(name="FakeSoulHandler")

    services = [
        MessageManager.initialize(fake_soul_handler),
        MessageDispatch.initialize(fake_soul_handler),
        RoomProfileManager.initialize(fake_soul_handler, drawer_driver=None),
        CommandManager.initialize(fake_soul_handler),
        PlaybackBroadcaster.initialize(fake_soul_handler),
        EventManager.initialize(fake_soul_handler),
        RecoveryManager.initialize(fake_soul_handler),
    ]

    for service in services:
        h = getattr(service, "handler", None) or getattr(service, "soul_handler", None)
        assert h is fake_soul_handler, (
            f"{service.__class__.__name__}.handler ({h}) is not "
            f"identically equal to injected fake_soul_handler ({fake_soul_handler})"
        )
