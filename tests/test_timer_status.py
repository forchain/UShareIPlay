import pytest

from ushareiplay.commands.timer import TimerCommand
from ushareiplay.managers.timer_manager import TimerManager
from ushareiplay.models.message_info import MessageInfo


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
    def __init__(self):
        self.soul_handler = _DummySoulHandler()
        self.music_handler = object()


def test_status_line_reports_stopped():
    tm = TimerManager.instance()

    assert tm.status_line() == "定时器: 已停止，共 0 个"


def test_status_line_reports_running_with_total_count():
    tm = TimerManager.instance()
    tm._running = True
    tm._timers = {"a": {}, "b": {}}

    assert tm.status_line() == "定时器: 运行中，共 2 个"


def test_status_line_reports_paused():
    tm = TimerManager.instance()
    tm._running = True
    tm._paused = True

    assert tm.status_line() == "定时器: 已暂停，共 0 个"


@pytest.mark.asyncio
async def test_timer_command_default_shows_status_instead_of_list():
    cmd = TimerCommand(_DummyController())
    msg = MessageInfo(content=":timer", nickname="Alice")

    result = await cmd.process(msg, [])

    assert result == {"timer": "定时器: 已停止，共 0 个"}


@pytest.mark.asyncio
async def test_timer_command_list_still_lists_timers():
    tm = TimerManager.instance()
    tm._timers = {
        "a": {"target_time": "08:00", "message": "早安", "enabled": True},
    }
    cmd = TimerCommand(_DummyController())
    msg = MessageInfo(content=":timer list", nickname="Alice")

    result = await cmd.process(msg, ["list"])

    assert "列表 (共1个)" in result["timer"]
