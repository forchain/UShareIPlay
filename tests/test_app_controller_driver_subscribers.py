import asyncio
from types import SimpleNamespace
from queue import Queue

import pytest

from ushareiplay.core.app_controller import AppController


class DriverAware:
    def __init__(self):
        self.driver = None


class FakeDriver:
    def __init__(self, name):
        self.name = name
        self.quit_called = False
        self.updated_settings = []

    def quit(self):
        self.quit_called = True

    def update_settings(self, settings):
        self.updated_settings.append(settings)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def debug(self, *args, **kwargs):
        self.messages.append(("debug", args, kwargs))

    def info(self, *args, **kwargs):
        self.messages.append(("info", args, kwargs))

    def warning(self, *args, **kwargs):
        self.messages.append(("warning", args, kwargs))

    def error(self, *args, **kwargs):
        self.messages.append(("error", args, kwargs))


class FakeObserver:
    def __init__(self):
        self.events = []

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs))


class FakeSoulHandler(DriverAware):
    def __init__(self):
        super().__init__()
        self.switch_to_app_called = False

    def switch_to_app(self):
        self.switch_to_app_called = True

    @property
    def key_actions(self):
        return self


def controller_without_init(driver=None):
    controller = AppController.__new__(AppController)
    controller.driver = driver or FakeDriver("old-driver")
    controller._driver_subscribers = []
    controller._is_reinitializing = False
    controller.logger = FakeLogger()
    controller.obs = FakeObserver()
    controller.soul_handler = None
    return controller


def test_controller_init_closes_driver_when_starting_apps_fails(monkeypatch):
    driver = FakeDriver("startup-driver")
    controller = object.__new__(AppController)
    monkeypatch.setattr(AppController, "_init_driver", lambda _self: driver)

    def fail_to_start_apps(_self):
        raise RuntimeError("startup failed")

    monkeypatch.setattr(AppController, "_start_apps", fail_to_start_apps)

    with pytest.raises(RuntimeError, match="startup failed"):
        AppController.__init__(controller, {})

    assert driver.quit_called is True


def test_register_driver_subscriber_adds_unique_objects_and_current_driver():
    controller = controller_without_init()
    subscriber = DriverAware()

    controller.register_driver_subscriber(subscriber)
    controller.register_driver_subscriber(subscriber)

    assert controller._driver_subscribers == [subscriber]
    assert subscriber.driver is controller.driver


def test_notify_driver_subscribers_sets_driver_on_each_registered_object():
    controller = controller_without_init()
    first = DriverAware()
    second = DriverAware()
    new_driver = SimpleNamespace(name="new-driver")

    controller.register_driver_subscriber(first)
    controller.register_driver_subscriber(second)
    controller._notify_driver_subscribers(new_driver)

    assert first.driver is new_driver
    assert second.driver is new_driver


def test_reinitialize_driver_notifies_registered_subscribers(monkeypatch):
    old_driver = FakeDriver("old-driver")
    new_driver = FakeDriver("new-driver")
    controller = controller_without_init(driver=old_driver)
    soul_handler = FakeSoulHandler()
    music_handler = DriverAware()
    music_manager = DriverAware()
    unregistered = DriverAware()
    controller.soul_handler = soul_handler
    controller.music_handler = music_handler
    controller.music_manager = music_manager

    controller.register_driver_subscriber(soul_handler)
    controller.register_driver_subscriber(music_handler)
    controller.register_driver_subscriber(music_manager)
    monkeypatch.setattr(controller, "_init_driver", lambda: new_driver)
    monkeypatch.setattr("ushareiplay.core.app_controller.time.sleep", lambda _: None)

    assert controller.reinitialize_driver() is True

    assert old_driver.quit_called is True
    assert controller.driver is new_driver
    assert soul_handler.driver is new_driver
    assert music_handler.driver is new_driver
    assert music_manager.driver is new_driver
    assert unregistered.driver is None
    assert soul_handler.switch_to_app_called is True
    assert new_driver.updated_settings == [
        {
            "waitForIdleTimeout": 0,
            "waitForSelectorTimeout": 2000,
            "waitForPageLoad": 2000,
        }
    ]


def test_controller_queues_dollar_command_with_injected_nickname(monkeypatch):
    from ushareiplay.core.app_controller import AppController
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.models.message_info import MessageInfo

    controller = controller_without_init()
    controller.input_queue = Queue()
    controller.soul_handler = FakeSoulHandler()
    controller.logger = FakeLogger()
    controller.obs = FakeObserver()
    controller.timer_manager = SimpleNamespace(is_running=lambda: True)
    controller._runtime_queue_drainer = None
    controller.event_manager = SimpleNamespace(
        get_page_source=lambda: "",
        process_events=lambda _page_source: None,
    )
    controller.is_running = False

    message_queue = MessageQueue.instance()
    asyncio.run(message_queue.clear_queue())

    controller.input_queue.put({
        "content": "$info",
        "source": "agent_spool",
        "nickname": "Outlier",
    })

    async def _noop():
        while not controller.input_queue.empty():
            item = controller.input_queue.get_nowait()
            if isinstance(item, dict):
                message = item.get("content", "")
                nickname = item.get("nickname", "Console")
            else:
                message = item
                nickname = "Console"
            trimmed = message.lstrip()
            if trimmed and trimmed[0] in (':', '：', '/', '／', '$', '＄') and trimmed[1:].strip():
                await MessageQueue.instance().put_message(
                    MessageInfo(content=trimmed, nickname=nickname)
                )

    asyncio.run(_noop())

    queued = asyncio.run(MessageQueue.instance().get_all_messages())
    assert [m.content for m in queued.values()] == ["$info"]
    assert [m.nickname for m in queued.values()] == ["Outlier"]


def test_monitor_loop_delegates_current_screen_processing_to_event_manager(monkeypatch):
    controller = controller_without_init()
    controller.config = {"commands": []}
    controller.input_queue = Queue()
    controller.soul_handler = SimpleNamespace(
        error_count=0,
        log_error=lambda *_args, **_kwargs: None,
        logger=SimpleNamespace(critical=lambda *_args, **_kwargs: None),
    )
    controller.logger = FakeLogger()
    controller.command_manager = SimpleNamespace(load_all_commands=lambda: None)

    async def _start_timer():
        return None

    controller.timer_manager = SimpleNamespace(is_running=lambda: True, start=_start_timer)
    controller._runtime_queue_drainer = None
    controller._drain_agent_command_spool = lambda: None
    controller.is_running = True
    controller.in_console_mode = False

    calls = []

    async def fake_update_status(_screen):
        calls.append("status")

    async def fake_process_current_screen():
        calls.append("processed")
        controller.is_running = False
        return {"page_source": "<hierarchy />", "screen": {}, "triggered_count": 0}

    controller.event_manager = SimpleNamespace(process_current_screen=fake_process_current_screen)
    controller._update_status_from_screen = fake_update_status

    def fail_get_page_source():
        raise AssertionError("monitor loop should not fetch page source directly")

    controller.event_manager.get_page_source = fail_get_page_source
    monkeypatch.setattr(controller, "_init_handlers", lambda: None)
    monkeypatch.setattr(
        "ushareiplay.managers.keyword_manager.KeywordManager.instance",
        lambda: SimpleNamespace(load_keywords_from_config=_start_timer),
    )
    monkeypatch.setattr(
        "ushareiplay.core.app_controller.threading.Thread",
        lambda target: SimpleNamespace(daemon=False, start=lambda: None),
    )

    async def noop_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("ushareiplay.core.app_controller.asyncio.sleep", noop_sleep)

    asyncio.run(controller.start_monitoring())

    assert calls == ["processed", "status"]


def test_monitor_loop_consumes_recovery_outcome_without_direct_recovery_policy(monkeypatch):
    controller = controller_without_init()
    controller.config = {"commands": []}
    controller.input_queue = Queue()
    controller.soul_handler = SimpleNamespace(
        error_count=0,
        log_error=lambda *_args, **_kwargs: None,
        logger=SimpleNamespace(critical=lambda *_args, **_kwargs: None),
    )
    controller.logger = FakeLogger()
    controller.command_manager = SimpleNamespace(load_all_commands=lambda: None)

    async def _start_timer():
        return None

    controller.timer_manager = SimpleNamespace(is_running=lambda: True, start=_start_timer)
    controller._runtime_queue_drainer = None
    controller._drain_agent_command_spool = lambda: None
    controller.is_running = True
    controller.in_console_mode = False
    calls = []

    async def fake_update_status(_screen):
        calls.append("status")

    async def fake_process_current_screen():
        calls.append("processed")
        controller.is_running = False
        return {
            "page_source": "<hierarchy />",
            "screen": {},
            "triggered_count": 0,
            "recovery": {
                "attempted": True,
                "suppressed": None,
                "pressed_back": True,
                "ready_rechecked": True,
                "backoff_seconds": 0.5,
            },
        }

    controller.event_manager = SimpleNamespace(process_current_screen=fake_process_current_screen)
    controller._update_status_from_screen = fake_update_status

    def fail_direct_recovery():
        raise AssertionError("monitor loop should not own recovery policy")

    controller.event_manager.get_page_source = fail_direct_recovery
    monkeypatch.setattr(controller, "_init_handlers", lambda: None)
    monkeypatch.setattr(
        "ushareiplay.managers.keyword_manager.KeywordManager.instance",
        lambda: SimpleNamespace(load_keywords_from_config=_start_timer),
    )
    monkeypatch.setattr(
        "ushareiplay.core.app_controller.threading.Thread",
        lambda target: SimpleNamespace(daemon=False, start=lambda: None),
    )

    async def noop_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("ushareiplay.core.app_controller.asyncio.sleep", noop_sleep)

    asyncio.run(controller.start_monitoring())

    assert calls == ["processed", "status"]
