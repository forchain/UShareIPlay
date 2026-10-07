"""
验证 Singleton 的创建、查找与重置契约。
"""
import threading
import pytest
from ushareiplay.core.singleton import Singleton, SingletonError


class _FooService(Singleton):
    pass


class _BarService(Singleton):
    pass


@pytest.fixture(autouse=True)
def reset_test_singletons():
    _FooService.reset_instance()
    _BarService.reset_instance()
    yield
    _FooService.reset_instance()
    _BarService.reset_instance()


def test_initialize_creates_instance_and_instance_returns_it():
    a = _FooService.initialize()
    b = _FooService.instance()
    assert a is b


def test_different_classes_are_independent():
    foo = _FooService.initialize()
    bar = _BarService.initialize()
    assert foo is not bar


def test_instance_before_initialize_raises_clear_error():
    with pytest.raises(SingletonError, match="_FooService has not been initialized"):
        _FooService.instance()


def test_initialize_twice_raises_clear_error():
    _FooService.initialize()

    with pytest.raises(SingletonError, match="_FooService singleton already initialized"):
        _FooService.initialize()


def test_instance_rejects_constructor_arguments():
    with pytest.raises(TypeError):
        _FooService.instance("unexpected")


def test_direct_constructor_is_not_a_creation_api():
    with pytest.raises(SingletonError, match="Use _FooService.initialize"):
        _FooService()


def test_direct_constructor_rejects_creation_after_initialize():
    _FooService.initialize()

    with pytest.raises(SingletonError, match="Use _FooService.initialize"):
        _FooService()


def test_thread_safe_concurrent_creation():
    instances = []
    barrier = threading.Barrier(20)

    class _ConcurrentService(Singleton):
        pass

    _ConcurrentService.initialize()

    def create():
        barrier.wait()
        instances.append(_ConcurrentService.instance())

    threads = [threading.Thread(target=create) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(id(i) for i in instances)) == 1, "并发创建应返回同一实例"
    _ConcurrentService.reset_instance()


def test_seat_management_classes_follow_singleton_contract():
    from ushareiplay.managers.seat_manager import (
        SeatManager,
        SeatUIManager,
        SeatCheckManager,
        ReservationManager,
        SeatingManager,
    )

    seat_classes = [SeatUIManager, SeatCheckManager, ReservationManager, SeatingManager, SeatManager]
    for cls in seat_classes:
        cls.reset_instance()
        with pytest.raises(SingletonError, match=f"Use {cls.__name__}.initialize"):
            cls()

    # Initialize in dependency order
    ui = SeatUIManager.initialize(handler=None)
    check = SeatCheckManager.initialize(handler=None, seat_ui=ui)
    res = ReservationManager.initialize(handler=None)
    seating = SeatingManager.initialize(handler=None)
    sm = SeatManager.initialize(handler=None, seat_ui=ui, seat_check=check, reservation=res, seating=seating)

    assert SeatUIManager.instance() is ui
    assert SeatCheckManager.instance() is check
    assert ReservationManager.instance() is res
    assert SeatingManager.instance() is seating
    assert SeatManager.instance() is sm

    with pytest.raises(SingletonError, match="already initialized"):
        SeatManager.initialize()

    Singleton.reset_all_instances()
    for cls in seat_classes:
        with pytest.raises(SingletonError, match="has not been initialized"):
            cls.instance()


def test_all_protected_singletons_reject_direct_constructor_instantiation():
    """验证系统中所有受保护单例服务均拒绝直接构造，必须经由 initialize() 创建。"""
    from ushareiplay.core.app_controller import AppController
    from ushareiplay.core.message_dispatch import MessageDispatch
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.admin_manager import AdminManager
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.event_manager import EventManager
    from ushareiplay.managers.info_manager import InfoManager
    from ushareiplay.managers.keyword_manager import KeywordManager
    from ushareiplay.managers.memory_manager import MemoryManager
    from ushareiplay.managers.message_manager import MessageManager
    from ushareiplay.managers.mic_manager import MicManager
    from ushareiplay.managers.music_manager import MusicManager
    from ushareiplay.managers.party_manager import PartyManager
    from ushareiplay.managers.playback_muting import PlaybackMuting
    from ushareiplay.managers.playlist_adoption import PlaylistAdoption
    from ushareiplay.managers.recovery_manager import RecoveryManager
    from ushareiplay.managers.room_profile import RoomProfileManager
    from ushareiplay.managers.seat_manager import (
        ReservationManager,
        SeatCheckManager,
        SeatingManager,
        SeatManager,
        SeatUIManager,
    )
    from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
    from ushareiplay.managers.sleep_manager import SleepManager
    from ushareiplay.managers.timer_manager import TimerManager
    from ushareiplay.managers.user_manager import UserManager
    from ushareiplay.state.online_list_scraper import OnlineListScraper
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
    from ushareiplay.state.playlist_state import PlaylistState
    from ushareiplay.state.presence_tracker import PresenceTracker
    from ushareiplay.state.room_state import RoomState

    all_protected_classes = [
        AppController,
        MessageDispatch,
        MessageQueue,
        UserManager,
        SleepManager,
        RecoveryManager,
        MessageManager,
        MicManager,
        MusicManager,
        PlaybackMuting,
        TimerManager,
        CommandManager,
        RoomState,
        PresenceTracker,
        PlaylistState,
        PlaybackBroadcaster,
        OnlineListScraper,
        InfoManager,
        PartyManager,
        PlaylistAdoption,
        AdminManager,
        KeywordManager,
        EventManager,
        MemoryManager,
        SeatUIManager,
        SeatCheckManager,
        ReservationManager,
        SeatingManager,
        SeatManager,
        SeatObservationManager,
    ]

    for cls in all_protected_classes:
        with pytest.raises(SingletonError, match=f"Use {cls.__name__}.initialize"):
            cls()


