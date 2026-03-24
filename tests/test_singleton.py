"""
验证 Singleton 基类在重构后行为不变：
- 同类返回同一实例
- 不同类各自独立
- 多线程并发创建仍是同一实例
"""
import threading
import pytest
from ushareiplay.core.singleton import Singleton


class _FooService(Singleton):
    pass


class _BarService(Singleton):
    pass


def test_same_class_returns_same_instance():
    a = _FooService.instance()
    b = _FooService.instance()
    assert a is b


def test_different_classes_are_independent():
    foo = _FooService.instance()
    bar = _BarService.instance()
    assert foo is not bar


def test_direct_constructor_returns_same_instance():
    a = _FooService()
    b = _FooService()
    assert a is b


def test_thread_safe_concurrent_creation():
    instances = []
    barrier = threading.Barrier(20)

    class _ConcurrentService(Singleton):
        pass

    def create():
        barrier.wait()
        instances.append(_ConcurrentService.instance())

    threads = [threading.Thread(target=create) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(id(i) for i in instances)) == 1, "并发创建应返回同一实例"
