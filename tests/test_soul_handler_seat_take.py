"""Ticket #317: SoulHandler owns the seat *UI mechanics*.

Detecting the grab-mic entry, confirming it, and waiting for the seat to settle
are room UI actions, so they live on SoulHandler (docs/room.md: "New room UI
action: Add method to SoulHandler").

Who *asks* for a seat is `MicManager` — the seat pre-check before opening the
microphone is part of its interface, tested in tests/test_mic_manager.py.
"""

from ushareiplay.handlers.soul_handler import SoulHandler


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


class _Element:
    def __init__(self, events, name):
        self.events = events
        self.name = name

    def click(self):
        self.events.append(f"click:{self.name}")


class _ElementFinder:
    """Room UI stand-in: `grab_mic` exists exactly while the bot is off-seat."""

    def __init__(self, events, on_seat=False, disappear_after_grab=True, mic_desc="开麦按钮"):
        self.events = events
        self.on_seat = on_seat
        self.disappear_after_grab = disappear_after_grab
        self.mic_desc = mic_desc
        self.disappear_calls = []
        self._grab_mic = _Element(events, "grab_mic")
        self._confirm_mic = _Element(events, "confirm_mic")
        self._toggle_mic = _Element(events, "toggle_mic")

    def try_find_element(self, key, log=False, clickable=False):
        if key == "grab_mic" and not self.on_seat:
            return self._grab_mic
        return None

    def wait_for_element_clickable(self, key, timeout=None):
        if key == "grab_mic":
            return None if self.on_seat else self._grab_mic
        if key == "confirm_mic":
            return self._confirm_mic
        if key == "toggle_mic":
            return self._toggle_mic
        return None

    def wait_for_element_disappear(self, key, timeout=3.0, poll_frequency=0.1):
        self.disappear_calls.append((key, timeout))
        if key != "grab_mic":
            return True
        if self.disappear_after_grab:
            self.on_seat = True
        return self.on_seat

    def try_get_attribute(self, element, attribute):
        if element is self._toggle_mic and attribute == "content-desc":
            return self.mic_desc
        return None


def _make_handler(events, **kwargs):
    handler = SoulHandler.__new__(SoulHandler)
    handler.logger = _Logger()
    handler.element_finder = _ElementFinder(events, **kwargs)
    return handler


def test_is_on_seat_reads_the_grab_mic_entry():
    events = []
    assert _make_handler(events, on_seat=False).is_on_seat() is False
    assert _make_handler(events, on_seat=True).is_on_seat() is True


def test_ensure_on_seat_grabs_and_confirms_then_waits_for_the_seat():
    events = []
    handler = _make_handler(events, on_seat=False)

    assert handler.ensure_on_seat() is True

    assert events == ["click:grab_mic", "click:confirm_mic"]
    assert handler.element_finder.disappear_calls == [("grab_mic", SoulHandler.SEAT_SETTLE_TIMEOUT)]


def test_ensure_on_seat_is_a_noop_when_already_seated():
    events = []
    handler = _make_handler(events, on_seat=True)

    assert handler.ensure_on_seat() is True

    assert events == []
    assert handler.element_finder.disappear_calls == []


def test_ensure_on_seat_reports_failure_when_the_grab_entry_stays():
    events = []
    handler = _make_handler(events, on_seat=False, disappear_after_grab=False)

    assert handler.ensure_on_seat() is False

    assert events == ["click:grab_mic", "click:confirm_mic"]


# 「确保开麦」的三例（抢麦 / 点开 / 已开不点）已迁到 tests/test_mic_manager.py：
# 麦克风状态与开关归 MicManager，本文件只留 SoulHandler 自己的麦位 UI 动作。
