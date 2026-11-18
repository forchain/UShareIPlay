import asyncio
from types import SimpleNamespace

import pytest

from ushareiplay.adapters.inbound.ui_events.chat_room_title import ChatRoomTitleEvent
from tests.room_profile_support import RoomProfileManager


class FakeLogger:
    def __init__(self):
        self.debug_messages = []

    def debug(self, message):
        self.debug_messages.append(message)


class FakeHandler:
    def __init__(self, room_profile_manager=None):
        self.logger = FakeLogger()
        self.controller = SimpleNamespace(
            room_state=None, room_profile_manager=room_profile_manager
        )


class FakeRuntime:
    def __init__(self, busy):
        self.busy = busy
        self.calls = 0

    def is_ui_busy(self):
        self.calls += 1
        return self.busy


def test_chat_room_title_skips_room_profile_manager_when_runtime_ui_busy():
    runtime = FakeRuntime(busy=True)

    class _UntouchedRoomProfileManager:
        def __getattr__(self, name):
            pytest.fail("room profile manager must not be touched while UI is busy")

    event = ChatRoomTitleEvent(
        FakeHandler(_UntouchedRoomProfileManager()), runtime=runtime
    )

    handled = asyncio.run(event.handle("chat_room_title", None))

    assert handled is False
    assert runtime.calls == 1


def test_chat_room_title_busy_skip_does_not_consume_throttle():
    runtime = FakeRuntime(busy=True)
    room_profile_manager_calls = 0

    class FakeRoomProfileManager:
        def get_next_title(self):
            nonlocal room_profile_manager_calls
            room_profile_manager_calls += 1
            return None

        def get_room_title_text_from_ui(self):
            nonlocal room_profile_manager_calls
            room_profile_manager_calls += 1
            return None

    event = ChatRoomTitleEvent(
        FakeHandler(FakeRoomProfileManager()), runtime=runtime
    )

    first_handled = asyncio.run(event.handle("chat_room_title", None))
    runtime.busy = False
    second_handled = asyncio.run(event.handle("chat_room_title", None))

    assert first_handled is False
    assert second_handled is False
    assert runtime.calls == 2
    assert room_profile_manager_calls == 0


def test_chat_room_title_uses_event_snapshot_instead_of_live_lookup(monkeypatch):
    runtime = FakeRuntime(busy=False)
    live_lookup_calls = 0

    class FakeRoomProfileManager:
        def get_next_title(self):
            return None
        theme_manager = None

        def get_room_title_text_from_ui(self):
            nonlocal live_lookup_calls
            live_lookup_calls += 1
            return "wrong live value"

    fake = FakeRoomProfileManager()
    event = ChatRoomTitleEvent(FakeHandler(fake), runtime=runtime)
    wrapper = type("Wrapper", (), {"content": "享乐｜Radio"})()

    assert asyncio.run(event.handle("chat_room_title", wrapper)) is False
    assert live_lookup_calls == 0


def test_chat_room_title_prefers_visible_title_over_content_description(monkeypatch):
    queued_titles = []

    class FakeRoomProfileManager:
        def get_next_title(self):
            return None

        def set_title(self, title):
            queued_titles.append(title)

    fake = FakeRoomProfileManager()
    event = ChatRoomTitleEvent(FakeHandler(fake), runtime=FakeRuntime(busy=False))
    wrapper = type("Wrapper", (), {"text": "享乐｜即兴的华彩", "content": "房间名称：Joyer"})()

    assert asyncio.run(event.handle("chat_room_title", wrapper)) is False
    assert queued_titles == []


def test_chat_room_title_does_not_overwrite_pending_business_title(monkeypatch):
    runtime = FakeRuntime(busy=False)
    queued_titles = []

    class FakeRoomProfileManager:
        def get_next_title(self):
            return "老夫妇"
        theme_manager = None

        def set_title(self, title):
            queued_titles.append(title)

    fake = FakeRoomProfileManager()
    event = ChatRoomTitleEvent(FakeHandler(fake), runtime=runtime)
    wrapper = type("Wrapper", (), {"content": "旧房名"})()

    assert asyncio.run(event.handle("chat_room_title", wrapper)) is False
    assert queued_titles == []


def test_chat_room_title_queues_configured_default_title(monkeypatch):
    runtime = FakeRuntime(busy=False)
    queued_titles = []

    class FakeRoomProfileManager:
        def get_next_title(self):
            return None
        theme_manager = None

        def get_default_title(self):
            return "自定义日推"

        def set_title(self, title):
            queued_titles.append(title)

    fake = FakeRoomProfileManager()
    event = ChatRoomTitleEvent(FakeHandler(fake), runtime=runtime)
    wrapper = type("Wrapper", (), {"content": "旧无分隔符房名"})()

    assert asyncio.run(event.handle("chat_room_title", wrapper)) is False
    assert queued_titles == ["自定义日推"]
