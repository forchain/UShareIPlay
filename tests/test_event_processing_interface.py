import asyncio
from types import SimpleNamespace

from ushareiplay.core.runtime_services import StatusReporter
from ushareiplay.managers.event_manager import EventManager


class FakeObserver:
    def __init__(self):
        self.statuses = []
        self.events = []

    def write_status(self, status):
        self.statuses.append(status)

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs))


class FakeAutomation:
    def __init__(self):
        self.ready_calls = 0

    async def on_command_ready(self):
        self.ready_calls += 1


class FakeLogger:
    def debug(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


def make_event_manager(config=None):
    manager = EventManager.__new__(EventManager)
    manager._handler = SimpleNamespace(
        logger=FakeLogger(),
        config=config
        or {
            "package_name": "cn.soulapp.android",
            "launcher_packages": [],
            "qq_music": {"package_name": "com.tencent.qqmusic"},
            "soul": {
                "elements": {
                    "message_content": "com.app:id/message_content",
                    "input_box_entry": "com.app:id/input_box_entry",
                    "input_box": "com.app:id/input_box",
                }
            },
        },
    )
    manager._logger = manager._handler.logger
    manager._config = manager._handler.config
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    manager.events_path = None
    manager.event_modules = {}
    manager.element_to_event = {}
    manager._initialized = True
    manager._consecutive_unknown_pages = 0
    return manager


def test_describe_screen_classifies_soul_chat_ready_page():
    manager = make_event_manager()
    page_source = """
    <hierarchy>
      <node package="cn.soulapp.android" resource-id="com.app:id/message_content" />
      <node package="cn.soulapp.android" resource-id="com.app:id/input_box" />
    </hierarchy>
    """

    screen = manager.describe_screen(page_source)

    assert screen["foreground_app"] == "Soul"
    assert screen["soul_ui_state"] == "InChatReady"
    assert screen["anchors"] == ["message_content", "input_box"]


def test_process_current_screen_retries_empty_page_source_and_returns_outcome(monkeypatch):
    manager = make_event_manager()
    page_source = """
    <hierarchy>
      <node package="cn.soulapp.android" resource-id="com.app:id/message_content" />
    </hierarchy>
    """
    page_sources = ["", page_source]
    processed = []

    def fake_get_page_source():
        return page_sources.pop(0)

    async def fake_react_to_page(source):
        processed.append(source)
        return {
            "triggered_count": 2,
            "recovery": {
                "attempted": False,
                "suppressed": None,
                "pressed_back": False,
                "ready_rechecked": False,
                "backoff_seconds": 0,
            },
        }

    async def noop_sleep(_seconds):
        return None

    manager.get_page_source = fake_get_page_source
    manager.react_to_page = fake_react_to_page
    monkeypatch.setattr("ushareiplay.managers.event_manager.asyncio.sleep", noop_sleep)

    outcome = asyncio.run(manager.process_current_screen())

    assert outcome == {
        "page_source": page_source,
        "screen": {
            "foreground_app": "Soul",
            "soul_ui_state": "InChatReady",
            "qqmusic_ui_state": "Unknown",
            "anchors": ["message_content"],
        },
        "triggered_count": 2,
        "recovery": {
            "attempted": False,
            "suppressed": None,
            "pressed_back": False,
            "ready_rechecked": False,
            "backoff_seconds": 0,
        },
    }
    assert processed == [page_source]


def test_process_current_screen_without_page_source_reports_no_page_source_recovery(monkeypatch):
    manager = make_event_manager()

    async def noop_sleep(_seconds):
        return None

    manager.get_page_source = lambda: ""
    monkeypatch.setattr("ushareiplay.managers.event_manager.asyncio.sleep", noop_sleep)

    outcome = asyncio.run(manager.process_current_screen())

    assert outcome == {
        "page_source": None,
        "screen": {
            "foreground_app": "Unknown",
            "soul_ui_state": "Unknown",
            "qqmusic_ui_state": "Unknown",
            "anchors": [],
        },
        "triggered_count": 0,
        "recovery": {
            "attempted": False,
            "suppressed": "no_page_source",
            "pressed_back": False,
            "ready_rechecked": False,
            "backoff_seconds": 0,
        },
    }


def test_process_current_screen_reports_ui_busy_suppressed_recovery(monkeypatch):
    manager = make_event_manager()
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: True)

    async def fake_process_once(_page_source):
        return 0

    async def fail_wait_ready(**_kwargs):
        raise AssertionError("should not recheck ready page while ui is busy")

    manager._process_events_once = fake_process_once
    manager._wait_page_source_ready_async = fail_wait_ready
    manager.handler.switch_to_app = lambda: (_ for _ in ()).throw(
        AssertionError("should not switch app while ui is busy")
    )
    manager.handler.press_back = lambda: (_ for _ in ()).throw(
        AssertionError("should not press back while ui is busy")
    )

    outcome = asyncio.run(manager.react_to_page("<hierarchy />"))

    assert outcome == {
        "triggered_count": 0,
        "recovery": {
            "attempted": False,
            "suppressed": "ui_busy",
            "pressed_back": False,
            "ready_rechecked": False,
            "backoff_seconds": 0,
        },
    }


def test_process_current_screen_reports_unknown_page_recovery_actions(monkeypatch):
    manager = make_event_manager()
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    manager._consecutive_unknown_pages = 10
    pressed_back = []
    switch_calls = []
    process_calls = []
    sleep_calls = []

    async def fake_process_once(page_source):
        process_calls.append(page_source)
        return 0

    async def fake_wait_ready(**_kwargs):
        return "<ready />"

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        return None

    manager._process_events_once = fake_process_once
    manager._wait_page_source_ready_async = fake_wait_ready
    manager.handler.switch_to_app = lambda: switch_calls.append(True)
    manager.handler.press_back = lambda: pressed_back.append(True)
    monkeypatch.setattr("ushareiplay.managers.event_manager.asyncio.sleep", fake_sleep)

    outcome = asyncio.run(manager.react_to_page("<initial />"))

    assert outcome == {
        "triggered_count": 0,
        "recovery": {
            "attempted": True,
            "suppressed": None,
            "pressed_back": True,
            "ready_rechecked": True,
            "backoff_seconds": 0.5,
        },
    }
    assert process_calls == ["<initial />", "<ready />"]
    assert switch_calls == [True]
    assert pressed_back == [True]
    assert sleep_calls == [0.5]


def test_react_to_page_reports_second_pass_trigger_count_when_ready_recheck_handles_event():
    manager = make_event_manager()
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    switch_calls = []
    process_calls = []

    async def fake_process_once(page_source):
        process_calls.append(page_source)
        return 0 if page_source == "<initial />" else 1

    async def fake_wait_ready(**_kwargs):
        return "<ready />"

    manager._process_events_once = fake_process_once
    manager._wait_page_source_ready_async = fake_wait_ready
    manager.handler.switch_to_app = lambda: switch_calls.append(True)
    manager.handler.press_back = lambda: (_ for _ in ()).throw(
        AssertionError("should not press back when ready recheck already handled an event")
    )

    outcome = asyncio.run(manager.react_to_page("<initial />"))

    assert outcome == {
        "triggered_count": 1,
        "recovery": {
            "attempted": True,
            "suppressed": None,
            "pressed_back": False,
            "ready_rechecked": True,
            "backoff_seconds": 0,
        },
    }
    assert process_calls == ["<initial />", "<ready />"]
    assert switch_calls == [True]


def test_status_reporter_uses_supplied_screen_description():
    obs = FakeObserver()
    reporter = StatusReporter(
        config={"soul": {"default_party_id": "123"}},
        ui_lock=SimpleNamespace(locked=lambda: False),
        obs=obs,
        soul_handler=SimpleNamespace(party_id="456"),
        timer_manager=SimpleNamespace(is_running=lambda: True),
    )
    automation = FakeAutomation()

    asyncio.run(
        reporter.update(
            screen={
                "foreground_app": "Soul",
                "soul_ui_state": "InChatReady",
                "qqmusic_ui_state": "Unknown",
                "anchors": ["message_content"],
            },
            automation=automation,
        )
    )

    assert obs.statuses == [
        {
            "foreground_app": "Soul",
            "soul_ui_state": "InChatReady",
            "qqmusic_ui_state": "Unknown",
            "anchors": ["message_content"],
            "pipeline": {"ui_lock": "unlocked", "queue_size": 0},
            "business": {
                "party_id_current": "456",
                "party_id_target": "123",
                "timers_running": True,
                "playback_info_summary": None,
            },
        }
    ]
    assert [event[0] for event in obs.events] == ["state.snapshot", "state.ready"]
    assert automation.ready_calls == 1
