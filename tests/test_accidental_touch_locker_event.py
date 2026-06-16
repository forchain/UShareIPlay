import pytest

from ushareiplay.events import accidental_touch_locker
from ushareiplay.events.accidental_touch_locker import AccidentalTouchLockerEvent


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class FakeLockerElement:
    location = {"x": 20, "y": 500}
    size = {"width": 40, "height": 40}


class FakeDriver:
    def get_window_size(self):
        return {"width": 1080, "height": 2400}

    def find_element(self, locator_type, locator_value):
        raise Exception("locker dismissed")


class FakeHandler:
    def __init__(self):
        self.logger = FakeLogger()
        self.controller = object()
        self.driver = FakeDriver()
        self.wait_calls = []
        self.swipes = []

    def wait_for_element(self, element_key, timeout=10):
        self.wait_calls.append((element_key, timeout))
        assert element_key == "accidental_touch_locker"
        return FakeLockerElement()

    def _perform_swipe(self, start_x, start_y, end_x, end_y, duration_ms=300):
        self.swipes.append((start_x, start_y, end_x, end_y, duration_ms))
        return True


@pytest.mark.asyncio
async def test_accidental_touch_locker_uses_configured_element_key(monkeypatch):
    monkeypatch.setattr(accidental_touch_locker.time, "sleep", lambda seconds: None)
    handler = FakeHandler()
    event = AccidentalTouchLockerEvent(handler)

    result = await event.handle("accidental_touch_locker", None)

    assert result is True
    assert handler.wait_calls == [("accidental_touch_locker", 3)]
    assert handler.swipes == [(40, 520, 40, 240, 400)]
