import asyncio
from types import SimpleNamespace

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.managers.event_manager import EventManager


SOUL_PAGE = '<hierarchy><node package="cn.soulapp.android" /></hierarchy>'


class FakeLogger:
    def __init__(self):
        self.debug_messages = []
        self.warning_messages = []
        self.error_messages = []

    def debug(self, message):
        self.debug_messages.append(message)

    def warning(self, message):
        self.warning_messages.append(message)

    def error(self, message):
        self.error_messages.append(message)


class FakeHandler:
    def __init__(self):
        self.logger = FakeLogger()
        self.controller = object()
        self.config = {
            "package_name": "cn.soulapp.android",
            "elements": {},
        }
        self.driver = SimpleNamespace(page_source=SOUL_PAGE)
        self.switch_to_app_calls = 0
        self.press_back_calls = 0

    def switch_to_app(self):
        self.switch_to_app_calls += 1
        return True

    def press_back(self):
        self.press_back_calls += 1
        return True


class FakeRuntime:
    def __init__(self, busy):
        self.busy = busy
        self.calls = 0

    def is_ui_busy(self):
        self.calls += 1
        return self.busy


def make_event_manager(runtime):
    manager = EventManager.__new__(EventManager)
    manager._handler = FakeHandler()
    manager._logger = manager._handler.logger
    manager._config = manager._handler.config
    manager._runtime = runtime
    manager.events_path = None
    manager.event_modules = {}
    manager.element_to_event = {}
    manager._initialized = True
    manager._consecutive_unknown_pages = 0
    return manager


def test_event_manager_skips_auto_back_when_runtime_ui_busy():
    runtime = FakeRuntime(busy=True)
    manager = make_event_manager(runtime)

    triggered = asyncio.run(manager.process_events(SOUL_PAGE))

    assert triggered == 0
    assert runtime.calls == 1
    assert manager.handler.switch_to_app_calls == 0
    assert manager.handler.press_back_calls == 0
    assert manager._consecutive_unknown_pages == 0


def test_event_manager_switches_to_app_and_presses_back_when_runtime_ui_not_busy():
    runtime = FakeRuntime(busy=False)
    manager = make_event_manager(runtime)

    triggered = asyncio.run(manager.process_events(SOUL_PAGE))

    assert triggered == 0
    assert runtime.calls == 1
    assert manager.handler.switch_to_app_calls >= 1
    assert manager.handler.press_back_calls == 1
    assert manager._consecutive_unknown_pages == 1


def test_base_event_accepts_runtime_and_preserves_controller_behavior():
    runtime = FakeRuntime(busy=True)
    handler = FakeHandler()

    event = BaseEvent(handler, runtime=runtime)

    assert event.handler is handler
    assert event.controller is handler.controller
    assert event.runtime is runtime
    assert event.is_ui_busy() is True
    assert runtime.calls == 1


def test_base_event_without_runtime_reports_ui_available():
    handler = FakeHandler()

    event = BaseEvent(handler)

    assert event.is_ui_busy() is False
