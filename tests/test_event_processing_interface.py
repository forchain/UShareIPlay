import asyncio
from types import SimpleNamespace

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.runtime_services import StatusReporter
from ushareiplay.managers.event_manager import EventManager
from ushareiplay.core.config_view import ConfigSectionView, ConfigView


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
        # handler 手里的是 soul 段视图（生产上组合根注入的就是它）。
        config=ConfigSectionView(
            "soul",
            config
            or {
                "package_name": "cn.soulapp.android",
                "launcher_packages": [],
                "elements": {
                    "message_content": "com.app:id/message_content",
                    "input_box_entry": "com.app:id/input_box_entry",
                    "input_box": "com.app:id/input_box",
                },
            },
        ),
    )
    manager._handler.key_actions = SimpleNamespace(
        switch_to_app=lambda: True,
        press_back=lambda: True,
        close_app=lambda: True,
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
            "force_closed": False,
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
    manager.handler.key_actions.switch_to_app = lambda: (_ for _ in ()).throw(
        AssertionError("should not switch app while ui is busy")
    )
    manager.handler.key_actions.press_back = lambda: (_ for _ in ()).throw(
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
            "force_closed": False,
        },
    }


def test_process_current_screen_reports_unknown_page_recovery_actions(monkeypatch):
    manager = make_event_manager()
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    manager._consecutive_unknown_pages = 0
    pressed_back = []
    switch_calls = []
    process_calls = []

    async def fake_process_once(page_source):
        process_calls.append(page_source)
        return 0

    async def fake_wait_ready(**_kwargs):
        return "<ready />"

    manager._process_events_once = fake_process_once
    manager._wait_page_source_ready_async = fake_wait_ready
    manager.handler.key_actions.switch_to_app = lambda: switch_calls.append(True)
    manager.handler.key_actions.press_back = lambda: pressed_back.append(True)

    outcome = asyncio.run(manager.react_to_page("<initial />"))

    assert outcome == {
        "triggered_count": 0,
        "recovery": {
            "attempted": True,
            "suppressed": None,
            "pressed_back": True,
            "ready_rechecked": True,
            "backoff_seconds": 0,
            "force_closed": False,
        },
    }
    assert process_calls == ["<initial />", "<ready />"]
    assert switch_calls == [True]
    assert pressed_back == [True]
    assert manager._consecutive_unknown_pages == 1


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
    manager.handler.key_actions.switch_to_app = lambda: switch_calls.append(True)
    manager.handler.key_actions.press_back = lambda: (_ for _ in ()).throw(
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
            "force_closed": False,
        },
    }
    assert process_calls == ["<initial />", "<ready />"]
    assert switch_calls == [True]


def test_react_to_page_force_closes_app_on_reaching_consecutive_threshold():
    manager = make_event_manager()
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    manager._consecutive_unknown_pages = 9
    pressed_back = []
    closed_app = []

    async def fake_process_once(_page_source):
        return 0

    async def fake_wait_ready(**_kwargs):
        return "<ready />"

    manager._process_events_once = fake_process_once
    manager._wait_page_source_ready_async = fake_wait_ready
    manager.handler.key_actions.press_back = lambda: pressed_back.append(True)
    manager.handler.key_actions.close_app = lambda: closed_app.append(True)

    outcome = asyncio.run(manager.react_to_page("<initial />"))

    assert outcome["recovery"]["pressed_back"] is True
    assert outcome["recovery"]["force_closed"] is True
    assert pressed_back == [True]
    assert closed_app == [True]
    assert manager._consecutive_unknown_pages == 0


def test_react_to_page_resets_counter_and_suppresses_back_when_switched_from_launcher():
    manager = make_event_manager()
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    manager._consecutive_unknown_pages = 5
    switch_calls = []
    pressed_back = []
    closed_app = []

    launcher_source = """
    <hierarchy>
      <node package="com.sec.android.app.launcher" resource-id="com.sec.android.app.launcher:id/workspace" />
    </hierarchy>
    """

    async def fake_process_once(_page_source):
        return 0

    async def fake_wait_ready(**_kwargs):
        return "<ready />"

    manager._process_events_once = fake_process_once
    manager._wait_page_source_ready_async = fake_wait_ready
    manager.handler.key_actions.switch_to_app = lambda: switch_calls.append(True)
    manager.handler.key_actions.press_back = lambda: pressed_back.append(True)
    manager.handler.key_actions.close_app = lambda: closed_app.append(True)

    outcome = asyncio.run(manager.react_to_page(launcher_source))

    assert manager._consecutive_unknown_pages == 0
    assert outcome["recovery"]["suppressed"] == "switched_from_non_soul"
    assert outcome["recovery"]["pressed_back"] is False
    assert outcome["recovery"]["force_closed"] is False
    assert switch_calls == [True]
    assert pressed_back == []
    assert closed_app == []


def test_react_to_page_resets_counter_when_event_triggers():
    manager = make_event_manager()
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    manager._consecutive_unknown_pages = 9
    closed_app = []

    async def fake_process_once(_page_source):
        return 1

    manager._process_events_once = fake_process_once
    manager.handler.key_actions.close_app = lambda: closed_app.append(True)

    outcome = asyncio.run(manager.react_to_page("<initial />"))

    assert outcome["triggered_count"] == 1
    assert manager._consecutive_unknown_pages == 0
    assert outcome["recovery"]["force_closed"] is False
    assert closed_app == []


def test_status_reporter_uses_supplied_screen_description():
    asyncio.run(MessageQueue.instance().clear_queue())
    obs = FakeObserver()
    reporter = StatusReporter(
        config=ConfigView({"soul": {"default_party_id": "123"}}),
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
