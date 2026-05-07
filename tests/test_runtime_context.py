import asyncio
from contextlib import asynccontextmanager

from ushareiplay.core.runtime_context import (
    CommandRuntimeContext,
    DriverRecoveryContext,
    EventRuntimeContext,
)


class FakeObserver:
    def __init__(self):
        self.events = []

    def emit(self, name, **kwargs):
        self.events.append((name, kwargs))


class FakeController:
    def __init__(self):
        self.obs = FakeObserver()
        self.reinitialized = 0
        self.session_reasons = []
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def ui_session(self, reason):
        self.session_reasons.append(reason)
        async with self.lock:
            yield

    def reinitialize_driver(self):
        self.reinitialized += 1
        return True


def test_command_runtime_context_delegates_observer_and_controller():
    controller = FakeController()
    runtime = CommandRuntimeContext(controller=controller)

    runtime.emit("command.received", ctx={"prefix": ":play"})

    assert runtime.controller is controller
    assert controller.obs.events == [
        ("command.received", {"ctx": {"prefix": ":play"}})
    ]


def test_event_runtime_context_reports_ui_busy_from_lock():
    lock = asyncio.Lock()
    runtime = EventRuntimeContext(ui_lock=lock)

    assert runtime.is_ui_busy() is False

    async def lock_once():
        await lock.acquire()
        try:
            assert runtime.is_ui_busy() is True
        finally:
            lock.release()

    asyncio.run(lock_once())


def test_driver_recovery_context_delegates_reinitialize_and_observer():
    controller = FakeController()
    runtime = DriverRecoveryContext(
        reinitialize_driver=controller.reinitialize_driver,
        obs=controller.obs,
    )

    assert runtime.reinitialize_driver() is True
    runtime.emit("recovery.reinitialized", ctx={"method": "page_source"})

    assert controller.reinitialized == 1
    assert controller.obs.events == [
        ("recovery.reinitialized", {"ctx": {"method": "page_source"}})
    ]
