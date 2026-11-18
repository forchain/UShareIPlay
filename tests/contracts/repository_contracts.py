"""可复用的仓储契约场景。

每个场景只通过端口断言对外可见行为，因此同一份场景可以分别跑在内存替身和
Tortoise/SQLite 实现上。测试文件负责构造实现，这里只负责共享断言。
"""

from datetime import datetime

from ushareiplay.modules.timer.domain import Timer


def _timer(key: str, **overrides) -> Timer:
    data = dict(
        key=key,
        message="hello",
        target_time="08:30",
        repeat=False,
        enabled=True,
        next_trigger=datetime(2026, 1, 1, 8, 30),
    )
    data.update(overrides)
    return Timer(**data)


async def assert_create_and_get(repository):
    created = await repository.create(
        key="t1",
        message="hello",
        target_time="08:30",
        repeat=True,
        enabled=True,
        next_trigger=datetime(2026, 1, 1, 8, 30),
    )

    assert isinstance(created, Timer)
    assert created == _timer("t1", repeat=True)
    assert await repository.get_by_key("t1") == created
    assert await repository.get_by_key("missing") is None


async def assert_get_or_create_is_idempotent(repository):
    first, created = await repository.get_or_create(
        "t1", dict(message="hello", target_time="08:30")
    )
    second, created_again = await repository.get_or_create(
        "t1", dict(message="other", target_time="09:00")
    )

    assert created is True
    assert created_again is False
    assert second == first
    assert await repository.count() == 1


async def assert_list_all(repository):
    await repository.create(key="a", message="alpha", target_time="08:30")
    await repository.create(key="b", message="beta", target_time="09:30")

    timers = await repository.list_all()

    assert all(isinstance(timer, Timer) for timer in timers)
    assert sorted(timer.key for timer in timers) == ["a", "b"]
    assert {timer.key: timer.message for timer in timers} == {"a": "alpha", "b": "beta"}


async def assert_update_enabled_and_next_trigger(repository):
    await repository.create(key="t1", message="hello", target_time="08:30")
    next_trigger = datetime(2026, 2, 2, 9, 15)

    assert await repository.update_enabled("t1", False) is True
    assert (await repository.get_by_key("t1")).enabled is False

    assert await repository.update_next_trigger("t1", next_trigger) is True
    assert (await repository.get_by_key("t1")).next_trigger == next_trigger

    assert await repository.update_enabled("missing", False) is False
    assert await repository.update_next_trigger("missing", next_trigger) is False


async def assert_delete(repository):
    await repository.create(key="t1", message="hello", target_time="08:30")

    assert await repository.delete_by_key("t1") is True
    assert await repository.get_by_key("t1") is None
    assert await repository.delete_by_key("t1") is False


async def assert_count(repository):
    assert await repository.count() == 0

    await repository.create(key="a", message="alpha", target_time="08:30")
    await repository.create(key="b", message="beta", target_time="09:30")

    assert await repository.count() == 2
