from datetime import datetime

import pytest

from tests.fakes.fake_clock import FakeClock
from tests.fakes.in_memory_timer_repository import InMemoryTimerRepository
from tests.fakes.recording_timer_message_sink import RecordingTimerMessageSink
from ushareiplay.adapters.inbound.chat.timer import TimerCommand
from ushareiplay.modules.shared.message_info import MessageInfo
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


class _DummyController:
    def __init__(self, timer_use_cases):
        self.soul_handler = _DummySoulHandler()
        self.music_handler = object()
        self.timer_manager = timer_use_cases


def _use_cases():
    return TimerUseCases(
        repository=InMemoryTimerRepository(),
        clock=FakeClock(NOW),
        sink=RecordingTimerMessageSink(),
        logger=_DummyLogger(),
    )


@pytest.mark.asyncio
async def test_timer_command_default_shows_status_instead_of_list():
    cmd = TimerCommand(_DummyController(_use_cases()))
    msg = MessageInfo(content=":timer", nickname="Alice")

    result = await cmd.process(msg, [])

    assert result == {"timer": "定时器: 已停止，共 0 个"}


@pytest.mark.asyncio
async def test_timer_command_list_still_lists_timers():
    use_cases = _use_cases()
    await use_cases.create_timer(
        message="早安", target_time="08:00", repeat=False, key="a"
    )
    cmd = TimerCommand(_DummyController(use_cases))
    msg = MessageInfo(content=":timer list", nickname="Alice")

    result = await cmd.process(msg, ["list"])

    assert "列表 (共1个)" in result["timer"]
