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


def test_seat_management_follows_singleton_contract():
    """座位管理的唯一实现由 `SeatManager` 绑定为受保护单例。

    `SeatManager` 继承 `SeatSubsystem`（#536）：守卫、UI 会话锁与全部座位流程都在
    实现上，门面不再逐方法转发。`SeatSubsystem` 本身仍**不**是单例：它没有全局
    状态，同一进程里可以并存多个实例（接线层一个 + 单元测试各自一个）。
    """
    from ushareiplay.managers.seat_manager import SeatManager
    from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

    SeatManager.reset_instance()
    with pytest.raises(SingletonError, match="Use SeatManager.initialize"):
        SeatManager()

    sm = SeatManager.initialize(handler=None)

    assert SeatManager.instance() is sm
    assert isinstance(sm, SeatSubsystem)

    with pytest.raises(SingletonError, match="already initialized"):
        SeatManager.initialize()

    # 实现类不走单例契约：直接构造合法，也不提供 lookup-only 的 instance()。
    assert not issubclass(SeatSubsystem, Singleton)
    assert not hasattr(SeatSubsystem, "instance")
    assert SeatSubsystem(handler=None) is not SeatSubsystem(handler=None)

    Singleton.reset_all_instances()
    with pytest.raises(SingletonError, match="has not been initialized"):
        SeatManager.instance()


def test_all_protected_singletons_reject_direct_constructor_instantiation():
    """验证系统中所有受保护单例服务均拒绝直接构造，必须经由 initialize() 创建。"""
    from ushareiplay.core.app_controller import AppController
    from ushareiplay.core.message_dispatch import MessageDispatch
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
    from ushareiplay.managers.event_manager import EventManager
    from ushareiplay.managers.info_manager import InfoManager
    from ushareiplay.managers.message_manager import MessageManager
    from ushareiplay.managers.music_manager import MusicManager
    from ushareiplay.managers.party_manager import PartyManager
    from ushareiplay.managers.playback_muting import PlaybackMuting
    from ushareiplay.managers.playlist_session import PlaylistSession
    from ushareiplay.managers.recovery_manager import RecoveryManager
    from ushareiplay.managers.room_profile import RoomProfileManager
    from ushareiplay.managers.seat_manager import SeatManager
    from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
    from ushareiplay.managers.user_manager import UserManager
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster

    all_protected_classes = [
        AppController,
        MessageDispatch,
        MessageQueue,
        UserManager,
        RecoveryManager,
        MessageManager,
        MusicManager,
        PlaybackMuting,
        CommandManager,
        PlaylistSession,
        PlaybackBroadcaster,
        InfoManager,
        PartyManager,
        EventManager,
        SeatManager,
        SeatObservationManager,
    ]

    for cls in all_protected_classes:
        with pytest.raises(SingletonError, match=f"Use {cls.__name__}.initialize"):
            cls()


