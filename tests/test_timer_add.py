from datetime import datetime, timedelta

import pytest

from tests.fakes.fake_clock import FakeClock
from tests.fakes.in_memory_timer_repository import InMemoryTimerRepository
from ushareiplay.adapters.inbound.chat.timer import TimerCommand
from ushareiplay.adapters.inbound.runtime.timer_message_sink import (
    QueueTimerMessageSink,
)
from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
from ushareiplay.modules.timer.use_cases import TimerUseCases

NOW = datetime(2026, 1, 1, 12, 0, 0)


class _DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _DummySoulHandler:
    def __init__(self):
        self.logger = _DummyLogger()

    def log_error(self, *args, **kwargs):
        pass


def _timer_use_cases(clock=None):
    repository = InMemoryTimerRepository()
    use_cases = TimerUseCases(
        repository=repository,
        clock=clock or FakeClock(NOW),
        sink=QueueTimerMessageSink(MessageQueue()),
        logger=_DummyLogger(),
    )
    return use_cases, repository


class _DummyController:
    def __init__(self, timer_use_cases):
        self.soul_handler = _DummySoulHandler()
        self.music_handler = object()
        self.timer_manager = timer_use_cases


@pytest.mark.asyncio
async def test_create_timer_supports_numeric_delay():
    clock = FakeClock(NOW)
    use_cases, repository = _timer_use_cases(clock)

    timer = await use_cases.create_timer(
        message="hello", target_time="10", repeat=False, key="delay10"
    )

    assert timer.key == "delay10"
    assert timer.target_time == "10"
    assert clock.now() + timedelta(seconds=10) == timer.next_trigger
    assert await repository.get_by_key("delay10") == timer


@pytest.mark.asyncio
async def test_timer_command_add_without_id_generates_key(monkeypatch):
    use_cases, repository = _timer_use_cases()
    controller = _DummyController(use_cases)

    # 让生成器第一次冲突、第二次成功
    await use_cases.create_timer(message="existing", target_time="10", repeat=False, key="deadbeef")
    seq = iter(["deadbeef", "feedface"])

    def _fake_token_hex(n):
        return next(seq)

    monkeypatch.setattr("secrets.token_hex", _fake_token_hex)

    cmd = TimerCommand(controller)
    result = await cmd._add_timer(["10", "hi"])
    assert "timer" in result
    assert "ID: feedface" in result["timer"]

    row = await repository.get_by_key("feedface")
    assert row is not None
    assert row.message == "hi"


@pytest.mark.asyncio
async def test_timer_command_strips_grouping_quotes_in_message():
    use_cases, repository = _timer_use_cases()
    controller = _DummyController(use_cases)

    cmd = TimerCommand(controller)
    result = await cmd._add_timer(["t1", "1", '":play test"', "@Console"])
    assert "timer" in result

    row = await repository.get_by_key("t1")
    assert row is not None
    assert row.message == ":play test @Console"


@pytest.mark.asyncio
async def test_one_shot_timer_deleted_after_trigger():
    use_cases, repository = _timer_use_cases()

    await use_cases.create_timer(
        key="oneshot",
        message="hello",
        target_time="10",
        repeat=False,
    )

    await use_cases.fire_timer("oneshot")

    assert await repository.get_by_key("oneshot") is None
    assert use_cases.get_timer("oneshot") is None


@pytest.mark.asyncio
async def test_timer_command_translates_invalid_time_to_the_public_message():
    use_cases, _repository = _timer_use_cases()
    cmd = TimerCommand(_DummyController(use_cases))

    result = await cmd._add_timer(["bad", "25:00", "hello"])

    assert result == {
        "error": "时间格式错误：支持 HH:MM / HH:MM:SS，或纯数字 N 表示延迟 N 秒"
    }


@pytest.mark.asyncio
async def test_timer_command_translates_duplicate_key_to_the_public_message():
    use_cases, _repository = _timer_use_cases()
    await use_cases.create_timer(message="hello", target_time="10", key="t1")
    cmd = TimerCommand(_DummyController(use_cases))

    result = await cmd._add_timer(["t1", "10", "other"])

    assert result == {"error": 'ID "t1" 已存在'}
