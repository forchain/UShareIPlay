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
