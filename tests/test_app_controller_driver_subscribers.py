import asyncio
from types import SimpleNamespace
from queue import Queue

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


def controller_without_init(driver=None):
    controller = AppController.__new__(AppController)
    controller.driver = driver or FakeDriver("old-driver")
    controller._driver_subscribers = []
    controller._is_reinitializing = False
    controller.logger = FakeLogger()
    controller.obs = FakeObserver()
    controller.soul_handler = None
    return controller


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
    controller._update_status_from_page_source = lambda _page_source: None
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
