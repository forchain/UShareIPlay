"""定时器用例：只接内存仓储、假时钟和记录 sink，不碰数据库或系统时间。"""

from datetime import datetime, timedelta

import pytest

from tests.fakes.fake_clock import FakeClock
from tests.fakes.in_memory_timer_repository import InMemoryTimerRepository
from tests.fakes.recording_timer_message_sink import RecordingTimerMessageSink
from ushareiplay.modules.timer.domain import InvalidTimerSpec, Timer, TimerKeyConflict
from ushareiplay.modules.timer.use_cases import TimerUseCases

NOW = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def timer_env():
    clock = FakeClock(NOW)
    repository = InMemoryTimerRepository()
    sink = RecordingTimerMessageSink()
    return TimerUseCases(repository=repository, clock=clock, sink=sink), repository, clock, sink


async def test_create_timer_uses_the_injected_clock_and_persists(timer_env):
    use_cases, repository, _clock, _sink = timer_env

    timer = await use_cases.create_timer(message="hello", target_time="10", key="delay10")

    assert timer == Timer(key="delay10", message="hello", target_time="10", next_trigger=NOW + timedelta(seconds=10))
    assert await repository.get_by_key("delay10") == timer
    assert use_cases.get_timer("delay10") == timer


async def test_create_timer_rejects_invalid_time_and_duplicate_explicit_key(timer_env):
    use_cases, _repository, _clock, _sink = timer_env
    await use_cases.create_timer(message="hello", target_time="10", key="t1")

    with pytest.raises(InvalidTimerSpec):
        await use_cases.create_timer(message="hello", target_time="25:00", key="bad")

    with pytest.raises(TimerKeyConflict, match='ID "t1" 已存在'):
        await use_cases.create_timer(message="other", target_time="20", key="t1")


async def test_create_timer_retries_generated_keys_on_conflict(timer_env, monkeypatch):
    use_cases, _repository, _clock, _sink = timer_env
    await use_cases.create_timer(message="existing", target_time="10", key="deadbeef")
    sequence = iter(["deadbeef", "feedface"])
    monkeypatch.setattr("secrets.token_hex", lambda _n: next(sequence))

    timer = await use_cases.create_timer(message="hi", target_time="10")

    assert timer.key == "feedface"


async def test_start_loads_persisted_timers_so_they_survive_restart(timer_env):
    use_cases, repository, _clock, _sink = timer_env
    await repository.create(
        key="morning",
        message="早安",
        target_time="08:00",
        repeat=True,
        next_trigger=datetime(2026, 1, 2, 8, 0),
    )

    await use_cases.start()
    try:
        assert use_cases.is_running() is True
        assert use_cases.get_timer("morning").message == "早安"
    finally:
        await use_cases.stop()


async def test_start_prepares_storage_once(timer_env):
    class _CountingRepository(InMemoryTimerRepository):
        def __init__(self):
            super().__init__()
            self.prepare_calls = 0

        async def prepare(self):
            self.prepare_calls += 1

    clock = FakeClock(NOW)
    repository = _CountingRepository()
    use_cases = TimerUseCases(
        repository=repository, clock=clock, sink=RecordingTimerMessageSink()
    )

    await use_cases.start()
    await use_cases.stop()
    await use_cases.start()
    await use_cases.stop()

    assert repository.prepare_calls == 1


async def test_reload_rereads_the_repository(timer_env):
    use_cases, repository, _clock, _sink = timer_env
    await repository.create(key="a", message="alpha", target_time="08:00")

    count = await use_cases.reload()

    assert count == 1
    assert use_cases.get_timers().keys() == {"a"}


async def test_load_reschedules_expired_repeat_timers_but_not_one_shots(timer_env):
    use_cases, repository, clock, _sink = timer_env
    await repository.create(
        key="daily",
        message="daily",
        target_time="19:00",
        repeat=True,
        next_trigger=NOW - timedelta(days=3),
    )
    await repository.create(
        key="once",
        message="once",
        target_time="19:00",
        repeat=False,
        next_trigger=NOW - timedelta(days=3),
    )

    await use_cases.reload()

    assert (await repository.get_by_key("daily")).next_trigger > clock.now()
    assert (await repository.get_by_key("once")).next_trigger == NOW - timedelta(days=3)


async def test_one_shot_fire_delivers_and_deletes(timer_env):
    use_cases, repository, _clock, sink = timer_env
    await use_cases.create_timer(message=":say 时间到", target_time="10", key="once")

    result = await use_cases.fire_timer("once")

    assert result == {"fired": True}
    assert sink.messages == [
        {"content": ":say 时间到", "nickname": "Timer", "sleep_exempt": True}
    ]
    assert await repository.get_by_key("once") is None
    assert "once" not in use_cases.get_timers()


async def test_repeat_fire_advances_past_missed_days(timer_env):
    use_cases, repository, clock, sink = timer_env
    timer = await use_cases.create_timer(
        message="daily hello", target_time="19:00", repeat=True, key="daily"
    )
    scheduled = timer.next_trigger
    clock.advance(4 * 24 * 3600)

    await use_cases.fire_timer("daily")

    next_trigger = (await repository.get_by_key("daily")).next_trigger
    assert next_trigger > clock.now()
    assert next_trigger - scheduled >= timedelta(days=4)
    assert sink.messages[0]["content"] == "daily hello"


async def test_pause_blocks_delivery_and_resume_reschedules_expired_repeats(timer_env):
    use_cases, repository, clock, sink = timer_env
    await use_cases.create_timer(
        message="night", target_time="19:00", repeat=True, key="night"
    )
    clock.advance(2 * 24 * 3600)

    use_cases.pause()
    assert use_cases.is_paused() is True
    await use_cases.fire_timer("night")
    assert sink.messages == []

    await use_cases.resume()

    assert use_cases.is_paused() is False
    assert (await repository.get_by_key("night")).next_trigger > clock.now()


async def test_remove_and_fire_unknown_timer(timer_env):
    use_cases, repository, _clock, _sink = timer_env

    assert await use_cases.fire_timer("ghost") == {"error": "Timer ghost not found"}
    assert await use_cases.remove_timer("ghost") is False

    await use_cases.create_timer(message="hello", target_time="10", key="t1")
    assert await use_cases.remove_timer("t1") is True
    assert await repository.get_by_key("t1") is None


async def test_add_timer_keeps_the_legacy_low_level_entry_point(timer_env):
    use_cases, _repository, _clock, _sink = timer_env

    assert await use_cases.add_timer("t1", "hello", "10") is True
    assert use_cases.get_timer("t1") is not None


async def test_status_line_reports_stopped_running_and_paused(timer_env):
    use_cases, _repository, _clock, _sink = timer_env

    assert use_cases.status_line() == "定时器: 已停止，共 0 个"

    await use_cases.create_timer(message="a", target_time="10", key="a")
    await use_cases.create_timer(message="b", target_time="20", key="b")
    await use_cases.start()
    try:
        assert use_cases.status_line() == "定时器: 运行中，共 2 个"
        use_cases.pause()
        assert use_cases.status_line() == "定时器: 已暂停，共 2 个"
    finally:
        await use_cases.stop()
