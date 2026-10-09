import asyncio
from datetime import datetime, timedelta
import pytest

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.dal.timer_dao import TimerDAO
from ushareiplay.managers.timer_manager import TimerManager
from ushareiplay.models.message_info import MessageInfo


class _DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_timer_manager_pause_prevents_trigger():
    await MessageQueue.instance().clear_queue()
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    tm = TimerManager.instance()
    tm._logger = _DummyLogger()

    # Create a timer
    timer_data = {
        "key": "test_pause",
        "message": ":play 晴天",
        "target_time": "10",
        "repeat": False,
        "enabled": True,
        "next_trigger": (datetime.now() - timedelta(seconds=5)).isoformat(),
    }
    tm._timers["test_pause"] = timer_data

    # Pause timer manager
    tm.pause()
    assert tm.is_paused() is True

    # Attempt to trigger directly while paused
    await tm._trigger_timer("test_pause", timer_data)

    # MessageQueue must remain empty
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 0

    # Resume timer manager
    await tm.resume()
    assert tm.is_paused() is False

    # Now trigger works
    await tm._trigger_timer("test_pause", timer_data)
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 1
    assert list(messages.values())[0].content == ":play 晴天"

    await MessageQueue.instance().clear_queue()
    await manager.close()


@pytest.mark.asyncio
async def test_timer_loop_skips_triggering_while_paused():
    await MessageQueue.instance().clear_queue()
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    tm = TimerManager.instance()
    tm._logger = _DummyLogger()
    tm._running = True
    tm.pause()

    timer_data = {
        "key": "loop_test",
        "message": "/title 晚上好 回家",
        "target_time": "19:00",
        "repeat": False,
        "enabled": True,
        "next_trigger": (datetime.now() - timedelta(seconds=1)).isoformat(),
    }
    tm._timers["loop_test"] = timer_data

    # Start loop in background
    task = asyncio.create_task(tm._timer_loop())
    await asyncio.sleep(0.05)

    # MessageQueue must NOT contain any messages because loop is paused
    messages = await MessageQueue.instance().get_all_messages()
    assert len(messages) == 0

    # Stop loop
    await tm.stop()
    await MessageQueue.instance().clear_queue()
    await manager.close()


@pytest.mark.asyncio
async def test_timer_manager_resume_skips_expired_repeat_timers():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    tm = TimerManager.instance()
    tm._logger = _DummyLogger()

    # Past trigger time for a repeat timer
    past_trigger = datetime.now() - timedelta(hours=2)
    await TimerDAO.create(
        key="theme_home",
        message="/title 晚上好 回家",
        target_time="19:00",
        repeat=True,
        enabled=True,
        next_trigger=past_trigger,
    )

    tm._timers["theme_home"] = {
        "key": "theme_home",
        "message": "/title 晚上好 回家",
        "target_time": "19:00",
        "repeat": True,
        "enabled": True,
        "next_trigger": past_trigger.isoformat(),
    }

    tm.pause()
    assert tm.is_paused() is True

    # Resume should reschedule the repeat timer to the future
    await tm.resume()
    assert tm.is_paused() is False

    updated_nt_str = tm._timers["theme_home"]["next_trigger"]
    updated_nt = datetime.fromisoformat(updated_nt_str)
    assert updated_nt > datetime.now()

    db_row = await TimerDAO.get_by_key("theme_home")
    assert db_row.next_trigger > datetime.now()

    await manager.close()


@pytest.mark.asyncio
async def test_app_controller_monitor_loop_skips_queue_drainer_when_paused(monkeypatch):
    """When runtime_input is paused, _runtime_queue_drainer.drain() should not be invoked."""
    from types import SimpleNamespace
    from ushareiplay.core.app_controller import AppController

    controller = AppController.__new__(AppController)
    controller.config = {"commands": []}
    controller.logger = _DummyLogger()
    controller.soul_handler = SimpleNamespace(
        error_count=0,
        log_error=lambda *a, **kw: None,
        logger=SimpleNamespace(critical=lambda *a, **kw: None),
    )
    controller.command_manager = SimpleNamespace(load_all_commands=lambda: None)
    controller.timer_manager = SimpleNamespace(is_running=lambda: True, start=lambda: asyncio.sleep(0))
    controller.in_console_mode = False
    controller.is_running = True
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

    from queue import Queue
    controller._runtime_queue_drainer = _Drainer()
    controller.input_queue = Queue()
    controller.role_policy = SimpleNamespace(room_owner="Owner")
    controller.obs = None
    controller._dump_readonly_artifacts = None
    controller._send_screen_message = lambda _t: None

    monkeypatch.setattr(
        "ushareiplay.core.app_controller.RuntimeInputPipeline",
        lambda **_kwargs: _Pipeline(),
    )
    async def noop_sleep(*_args, **_kwargs):
        return None

    async def _async_noop():
        return None

    monkeypatch.setattr(
        "ushareiplay.core.app_controller.threading.Thread",
        lambda target: SimpleNamespace(daemon=False, start=lambda: None),
    )
    monkeypatch.setattr("ushareiplay.core.app_controller.asyncio.sleep", noop_sleep)
    monkeypatch.setattr(controller, "_init_handlers", lambda: None)
    monkeypatch.setattr(
        "ushareiplay.managers.keyword_manager.KeywordManager.instance",
        lambda: SimpleNamespace(load_keywords_from_config=_async_noop),
    )

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
