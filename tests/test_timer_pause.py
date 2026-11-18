import asyncio
from datetime import datetime, timedelta

import pytest

from tests.fakes.fake_clock import FakeClock
from tests.fakes.in_memory_timer_repository import InMemoryTimerRepository
from ushareiplay.adapters.inbound.runtime.timer_message_sink import (
    QueueTimerMessageSink,
)
from ushareiplay.adapters.outbound.system.clock import SystemClock
from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
from ushareiplay.modules.timer.use_cases import TimerUseCases

NOW = datetime(2026, 1, 1, 12, 0, 0)


class _DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def _use_cases(clock, repository=None, message_queue=None):
    queue = message_queue or MessageQueue()
    return TimerUseCases(
        repository=repository or InMemoryTimerRepository(),
        clock=clock,
        sink=QueueTimerMessageSink(queue),
        logger=_DummyLogger(),
    )


@pytest.mark.asyncio
async def test_timer_manager_pause_prevents_trigger():
    queue = MessageQueue()
    clock = FakeClock(NOW)
    repository = InMemoryTimerRepository()
    use_cases = _use_cases(clock, repository, queue)

    await use_cases.create_timer(
        key="test_pause", message=":play 晴天", target_time="10", repeat=False
    )

    # Pause timer manager
    use_cases.pause()
    assert use_cases.is_paused() is True

    # Attempt to trigger directly while paused
    await use_cases.fire_timer("test_pause")

    # MessageQueue must remain empty
    assert await queue.get_all_messages() == {}

    # Resume timer manager
    await use_cases.resume()
    assert use_cases.is_paused() is False

    # Now trigger works
    await use_cases.fire_timer("test_pause")
    messages = await queue.get_all_messages()
    assert len(messages) == 1
    assert next(iter(messages.values())).content == ":play 晴天"

    await queue.clear_queue()


@pytest.mark.asyncio
async def test_timer_loop_skips_triggering_while_paused():
    queue = MessageQueue()
    repository = InMemoryTimerRepository()
    await repository.create(
        key="loop_test",
        message="/title 晚上好 回家",
        target_time="19:00",
        repeat=False,
        enabled=True,
        next_trigger=datetime.now() - timedelta(seconds=1),
    )
    use_cases = _use_cases(SystemClock(), repository, queue)

    await use_cases.start()
    use_cases.pause()
    await asyncio.sleep(0.05)

    # MessageQueue must NOT contain any messages because loop is paused
    assert await queue.get_all_messages() == {}

    await use_cases.stop()
    await queue.clear_queue()


@pytest.mark.asyncio
async def test_timer_manager_resume_skips_expired_repeat_timers():
    clock = FakeClock(NOW)
    repository = InMemoryTimerRepository()
    use_cases = _use_cases(clock, repository)

    await use_cases.create_timer(
        key="theme_home",
        message="/title 晚上好 回家",
        target_time="19:00",
        repeat=True,
    )
    # 两天后才恢复：暂停期间的重复任务已积压。
    clock.advance(2 * 24 * 3600)

    use_cases.pause()
    assert use_cases.is_paused() is True

    # Resume should reschedule the repeat timer to the future
    await use_cases.resume()
    assert use_cases.is_paused() is False

    assert use_cases.get_timer("theme_home").next_trigger > clock.now()
    assert (await repository.get_by_key("theme_home")).next_trigger > clock.now()


@pytest.mark.asyncio
async def test_app_controller_monitor_loop_skips_queue_drainer_when_paused(monkeypatch):
    """When runtime_input is paused, _runtime_queue_drainer.drain() should not be invoked."""
    from types import SimpleNamespace

    from ushareiplay.bootstrap.runtime_loop import RuntimeLoop

    controller = RuntimeLoop(
        config={"commands": []},
        obs=None,
        lease=SimpleNamespace(lock=SimpleNamespace(locked=lambda: False)),
        room_owner_provider=lambda: "Owner",
    )
    controller.logger = _DummyLogger()
    controller.soul_handler = SimpleNamespace(
        error_count=0,
        log_error=lambda *a, **kw: None,
        logger=SimpleNamespace(critical=lambda *a, **kw: None),
    )
    controller.command_manager = SimpleNamespace(load_all_commands=lambda: None)
    controller.timer_manager = SimpleNamespace(is_running=lambda: True, start=lambda: asyncio.sleep(0))
    controller._drain_agent_command_spool = lambda: None

    drained_calls = []

    class _Drainer:
        async def drain(self):
            drained_calls.append(True)
            return 0, 0

    class _Pipeline:
        def __init__(self):
            self.paused = True
            self.drain_count = 0

        async def drain(self):
            self.drain_count += 1
            if self.drain_count >= 3:
                controller.is_running = False

        def register_interruption_hook(self, _hook):
            pass

    controller.runtime_queue_drainer = _Drainer()

    monkeypatch.setattr(
        "ushareiplay.bootstrap.runtime_loop.RuntimeInputPipeline",
        lambda **_kwargs: _Pipeline(),
    )
    async def noop_sleep(*_args, **_kwargs):
        return None

    async def _async_noop():
        return None

    monkeypatch.setattr(
        "ushareiplay.bootstrap.runtime_loop.threading.Thread",
        lambda target: SimpleNamespace(daemon=False, start=lambda: None),
    )
    monkeypatch.setattr("ushareiplay.bootstrap.runtime_loop.asyncio.sleep", noop_sleep)
    controller.keyword_use_cases = SimpleNamespace(load_keywords_from_config=_async_noop)

    processed_screens = []

    async def fake_process_screen():
        processed_screens.append(True)
        return {"page_source": "", "screen": {}, "triggered_count": 0}

    controller.event_manager = SimpleNamespace(process_current_screen=fake_process_screen)

    await controller.start_monitoring()

    # Drained calls and screen processing must both be 0 because runtime_input was paused
    assert len(drained_calls) == 0
    assert len(processed_screens) == 0
    assert controller.runtime_input.drain_count == 3
