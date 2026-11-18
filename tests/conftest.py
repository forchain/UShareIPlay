from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.fakes.in_memory_user_repository import InMemoryUserRepository
from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
from ushareiplay.adapters.inbound.runtime.message_manager import MessageManager
from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
from ushareiplay.adapters.inbound.ui_events.event_manager import EventManager
from ushareiplay.adapters.outbound.appium.soul.message_dispatch import MessageDispatch
from ushareiplay.adapters.outbound.system.clock import SystemClock
from ushareiplay.adapters.outbound.system.config_loader import ConfigLoader
from ushareiplay.modules.command.domain import CommandCatalogue
from ushareiplay.modules.playback.broadcaster import PlaybackBroadcaster
from ushareiplay.modules.room.use_cases import PresenceTracker, RoomStateService
from ushareiplay.modules.shared.config import ConfigSectionView


@pytest.fixture(autouse=True)
def initialized_test_singletons():
    """Build an explicit, isolated service graph for each test (no singletons)."""
    room_state = RoomStateService(
        catalogue=CommandCatalogue.from_config(ConfigLoader.load_config())
    )
    presence = PresenceTracker()
    message_queue = MessageQueue()
    message_dispatch = MessageDispatch()
    users = InMemoryUserRepository()
    clock = SystemClock()
    command_manager = CommandManager(
        room_state=room_state,
        users=users,
        clock=clock,
        message_dispatch=message_dispatch,
    )
    event_manager = EventManager()
    message_manager = MessageManager(
        presence=presence,
        message_queue=message_queue,
        command_manager=command_manager,
        users=users,
    )
    playback_broadcaster = PlaybackBroadcaster(messenger=message_dispatch)

    services = SimpleNamespace(
        room_state=room_state,
        presence=presence,
        message_queue=message_queue,
        message_dispatch=message_dispatch,
        command_manager=command_manager,
        event_manager=event_manager,
        message_manager=message_manager,
        playback_broadcaster=playback_broadcaster,
        user_repository=users,
        clock=clock,
    )
    yield services


@pytest.fixture
def room_state(initialized_test_singletons):
    """本测试共享的房间状态（与本图里的 CommandManager 同一份）。"""
    return initialized_test_singletons.room_state


@pytest.fixture
def presence(initialized_test_singletons):
    """本测试共享的在线集合。"""
    return initialized_test_singletons.presence


@pytest.fixture
def message_dispatch(initialized_test_singletons):
    """本测试共享的公屏出口（消息派发适配器）。"""
    return initialized_test_singletons.message_dispatch


@pytest.fixture
def chat_window(initialized_test_singletons):
    """聊天窗口测试台：真实的 MessageManager + 假 handler / chat_logger。"""
    chat_logger = MagicMock()
    controller = SimpleNamespace(
        room_state=initialized_test_singletons.room_state,
        presence=initialized_test_singletons.presence,
        message_queue=initialized_test_singletons.message_queue,
        message_dispatch=initialized_test_singletons.message_dispatch,
        command_manager=initialized_test_singletons.command_manager,
        message_manager=initialized_test_singletons.message_manager,
        playback_broadcaster=initialized_test_singletons.playback_broadcaster,
        user_repository=initialized_test_singletons.user_repository,
    )
    handler = SimpleNamespace(
        logger=MagicMock(),
        config=ConfigSectionView("soul", {"room_owner": "群主"}),
        controller=controller,
    )
    manager = initialized_test_singletons.message_manager
    manager._handler = handler
    manager._chat_logger = chat_logger
    return SimpleNamespace(
        manager=manager,
        logger=chat_logger,
        handler=handler,
        controller=controller,
        message_queue=initialized_test_singletons.message_queue,
        command_manager=initialized_test_singletons.command_manager,
    )
