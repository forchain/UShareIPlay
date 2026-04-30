import pytest


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


@pytest.mark.asyncio
async def test_timer_manager_supports_numeric_delay():
    from datetime import datetime, timedelta
    from ushareiplay.core.db_manager import DatabaseManager
    from ushareiplay.managers.timer_manager import TimerManager
    from ushareiplay.dal.timer_dao import TimerDAO

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    tm = TimerManager.instance()
    tm._logger = _DummyLogger()

    before = datetime.now()
    ok = await tm.add_timer("delay10", "hello", "10", repeat=False)
    assert ok is True

    row = await TimerDAO.get_by_key("delay10")
    assert row is not None
    assert row.target_time == "10"
    assert row.next_trigger is not None
    assert before + timedelta(seconds=8) <= row.next_trigger <= before + timedelta(seconds=20)

    await manager.close()


@pytest.mark.asyncio
async def test_timer_command_add_without_id_generates_key(monkeypatch):
    from ushareiplay.core.db_manager import DatabaseManager
    from ushareiplay.commands.timer import TimerCommand
    from ushareiplay.managers.timer_manager import TimerManager
    from ushareiplay.dal.timer_dao import TimerDAO

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    tm = TimerManager.instance()
    tm._logger = _DummyLogger()

    # 让生成器第一次冲突、第二次成功
    await tm.add_timer("deadbeef", "existing", "10", repeat=False)
    seq = iter(["deadbeef", "feedface"])

    def _fake_token_hex(n):
        return next(seq)

    monkeypatch.setattr("secrets.token_hex", _fake_token_hex)

    cmd = TimerCommand(_DummyController())
    result = await cmd._add_timer(["10", "hi"])
    assert "timer" in result
    assert "ID: feedface" in result["timer"]

    row = await TimerDAO.get_by_key("feedface")
    assert row is not None
    assert row.message == "hi"

    await manager.close()

