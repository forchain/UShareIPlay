import pytest

from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.event_manager import EventManager
from ushareiplay.managers.message_manager import MessageManager
from ushareiplay.managers.mic_manager import MicManager
from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.managers.playlist_adoption import PlaylistAdoption
from ushareiplay.managers.room_info_window import RoomInfoWindow
from ushareiplay.managers.timer_manager import TimerManager


@pytest.fixture(autouse=True)
def initialized_test_singletons():
    """Provide dependency-free singleton services and isolate every test."""
    Singleton.reset_all_instances()
    for singleton_class in (
        MessageQueue,
        MessageDispatch,
        CommandManager,
        EventManager,
        MessageManager,
        MicManager,
        PartyManager,
        PlaylistAdoption,
        RoomInfoWindow,
        TimerManager,
    ):
        singleton_class.initialize()

    yield

    Singleton.reset_all_instances()


@pytest.fixture
def chat_window():
    """聊天窗口测试台：真实的 MessageManager + 假 handler / chat_logger。

    聊天窗口的观察与派发现在都在 MessageManager 的接口后面，因此聊天流测试
    直接配置这个实例，而不是 monkeypatch 掉 `instance` 再往两个公有 deque 里
    塞数据（那等于绕开被观察的接口）。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    manager = MessageManager.instance()
    chat_logger = MagicMock()
    handler = SimpleNamespace(
        logger=MagicMock(),
        config={"soul": {"room_owner": "群主"}},
        controller=None,  # BaseEvent 会读它
    )
    manager._handler = handler
    manager._chat_logger = chat_logger
    return SimpleNamespace(manager=manager, logger=chat_logger, handler=handler)
