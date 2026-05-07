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
    assert title_manager_calls == 1
