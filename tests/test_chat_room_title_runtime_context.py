import asyncio

import pytest

from ushareiplay.events.chat_room_title import ChatRoomTitleEvent
from ushareiplay.managers.title_manager import TitleManager


class FakeLogger:
    def __init__(self):
        self.debug_messages = []

    def debug(self, message):
        self.debug_messages.append(message)


class FakeHandler:
    def __init__(self):
        self.logger = FakeLogger()
        self.controller = object()


class FakeRuntime:
    def __init__(self, busy):
        self.busy = busy
        self.calls = 0

    def is_ui_busy(self):
        self.calls += 1
        return self.busy


def test_chat_room_title_skips_title_manager_when_runtime_ui_busy(monkeypatch):
    runtime = FakeRuntime(busy=True)

    def fail_if_title_manager_is_touched():
        pytest.fail("TitleManager.instance should not be called while UI is busy")

    monkeypatch.setattr(TitleManager, "instance", fail_if_title_manager_is_touched)

    event = ChatRoomTitleEvent(FakeHandler(), runtime=runtime)

    handled = asyncio.run(event.handle("chat_room_title", None))

    assert handled is False
    assert runtime.calls == 1


def test_chat_room_title_busy_skip_does_not_consume_throttle(monkeypatch):
    runtime = FakeRuntime(busy=True)
    title_manager_calls = 0

    class FakeTitleManager:
        next_title = None

        def get_room_title_text_from_ui(self):
            return None

    def title_manager_instance():
        nonlocal title_manager_calls
        title_manager_calls += 1
        return FakeTitleManager()

    monkeypatch.setattr(TitleManager, "instance", title_manager_instance)

    event = ChatRoomTitleEvent(FakeHandler(), runtime=runtime)

    first_handled = asyncio.run(event.handle("chat_room_title", None))
    runtime.busy = False
    second_handled = asyncio.run(event.handle("chat_room_title", None))

    assert first_handled is False
    assert second_handled is False
    assert runtime.calls == 2
    assert title_manager_calls == 0


def test_chat_room_title_uses_event_snapshot_instead_of_live_lookup(monkeypatch):
    runtime = FakeRuntime(busy=False)
    live_lookup_calls = 0

    class FakeTitleManager:
        next_title = None
        theme_manager = None

        def get_room_title_text_from_ui(self):
            nonlocal live_lookup_calls
            live_lookup_calls += 1
            return "wrong live value"

    monkeypatch.setattr(TitleManager, "instance", lambda: FakeTitleManager())
    event = ChatRoomTitleEvent(FakeHandler(), runtime=runtime)
    wrapper = type("Wrapper", (), {"content": "享乐｜Radio"})()

    assert asyncio.run(event.handle("chat_room_title", wrapper)) is False
    assert live_lookup_calls == 0


def test_chat_room_title_does_not_overwrite_pending_business_title(monkeypatch):
    runtime = FakeRuntime(busy=False)
    queued_titles = []

    class FakeTitleManager:
        next_title = "老夫妇"
        theme_manager = None

        def set_next_title(self, title):
            queued_titles.append(title)

    monkeypatch.setattr(TitleManager, "instance", lambda: FakeTitleManager())
    event = ChatRoomTitleEvent(FakeHandler(), runtime=runtime)
    wrapper = type("Wrapper", (), {"content": "旧房名"})()

    assert asyncio.run(event.handle("chat_room_title", wrapper)) is False
    assert queued_titles == []
