import inspect

import pytest

from ushareiplay.modules.shared.config import ConfigSectionView
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
from ushareiplay.managers.event_manager import EventManager
from ushareiplay.managers.message_manager import MessageManager
from ushareiplay.managers.mic_manager import MicManager
from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.managers.playlist_session import PlaylistSession
from ushareiplay.managers.room_profile import RoomProfileManager
from tests import legacy_state


def _install_injected_default(cls, param, provider):
    """给旧单例构造器补一个「组合根默认值」，仅供测试。

    生产代码必须显式注入；大量既有行为测试仍调用零参 `initialize()`，
    这里让它们拿到当前测试共享的那一份房间状态 / 在线集合。
    """
    original = cls.__init__
    if getattr(original, "_test_default_param", None) == param:
        return
    signature = inspect.signature(original)

    def __init__(self, *args, **kwargs):
        if param in signature.parameters and param not in kwargs:
            try:
                bound = signature.bind_partial(self, *args, **kwargs)
            except TypeError:
                bound = None
            if bound is None or param not in bound.arguments:
                kwargs[param] = provider()
        original(self, *args, **kwargs)

    __init__._test_default_param = param
    cls.__init__ = __init__


def _install_room_profile_listener(cls):
    """组合根注册的换房副作用：房间 ID 变更时作废从 UI 读回的房间档案。"""
    original = cls.__init__
    if getattr(original, "_test_room_listener", False):
        return

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if self._room_state is not None:
            self._room_state.add_room_change_listener(self.invalidate_ui_state)

    __init__._test_room_listener = True
    cls.__init__ = __init__


def _install_state_defaults():
    from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
    from ushareiplay.managers.info_manager import InfoManager
    from ushareiplay.managers.keyword_manager import KeywordManager
    from ushareiplay.managers.message_manager import MessageManager
    from ushareiplay.managers.party_manager import PartyManager
    from ushareiplay.managers.playback_muting import PlaybackMuting
    from ushareiplay.managers.playlist_session import PlaylistSession
    from ushareiplay.managers.room_profile import RoomProfileManager
    from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
    from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

    for cls in (
        SeatSubsystem,
        PartyManager,
        RoomProfileManager,
        SeatObservationManager,
        KeywordManager,
        PlaybackMuting,
        CommandManager,
    ):
        _install_injected_default(cls, "room_state", legacy_state.room_state)
    for cls in (InfoManager, MessageManager):
        _install_injected_default(cls, "presence", legacy_state.presence)
    _install_injected_default(InfoManager, "room_state", legacy_state.room_state)
    _install_room_profile_listener(RoomProfileManager)
    _install_injected_default(
        InfoManager, "online_list_source", legacy_state.online_list_source
    )
    _install_injected_default(
        PlaylistSession,
        "online_users",
        lambda: legacy_state.presence().get_online_users,
    )


@pytest.fixture(autouse=True)
def initialized_test_singletons():
    """Provide dependency-free singleton services and isolate every test."""
    Singleton.reset_all_instances()
    legacy_state.reset_context()
    for singleton_class in (
        MessageQueue,
        MessageDispatch,
        CommandManager,
        EventManager,
        MessageManager,
        MicManager,
        PartyManager,
        PlaylistSession,
        RoomProfileManager,
    ):
        singleton_class.initialize()

    # 房间状态与在线集合在组合根各构造一次；零参单例拿到同一份共享实例。
    room_state = legacy_state.room_state()
    presence = legacy_state.presence()
    CommandManager.instance().room_state = room_state
    PartyManager.instance()._room_state = room_state
    RoomProfileManager.instance()._room_state = room_state
    MessageManager.instance()._presence = presence
    PlaylistSession.instance()._online_users = presence.get_online_users

    yield

    Singleton.reset_all_instances()


_install_state_defaults()


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
        config=ConfigSectionView("soul", {"room_owner": "群主"}),
        controller=None,  # BaseEvent 会读它
    )
    manager._handler = handler
    manager._chat_logger = chat_logger
    return SimpleNamespace(manager=manager, logger=chat_logger, handler=handler)
