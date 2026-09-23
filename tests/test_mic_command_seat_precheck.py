"""Ticket #317: opening the mic first makes sure the bot is on a seat.

Talking from the floor is impossible in the Soul party UI: while the bot is
off-seat the room only offers the grab-mic entry, so a blind click on the
mic toggle fails. `:mic 1` (and a bare `:mic` while off-seat) seat the bot
first, then open the microphone. `:mic 0` never touches the seat.

The seat UI mechanics themselves (grab entry, settle wait) live on
`SoulHandler`; see tests/test_soul_handler_seat_take.py.
"""

from types import SimpleNamespace

from ushareiplay.commands.mic import MicCommand


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _Element:
    def __init__(self, events, name):
        self.events = events
        self.name = name

    def click(self):
        self.events.append(f"click:{self.name}")


class _ElementFinder:
    def __init__(self, events, mic_desc="开麦按钮"):
        self.events = events
        self.mic_desc = mic_desc
        self.missing_toggle = False
        self._toggle_mic = _Element(events, "toggle_mic")

    def wait_for_element_clickable(self, key, timeout=None):
        if key == "toggle_mic":
            return None if self.missing_toggle else self._toggle_mic
        return None

    def try_get_attribute(self, element, attribute):
        if element is self._toggle_mic and attribute == "content-desc":
            return self.mic_desc
        return None


class _SoulHandler:
    """Stands in for SoulHandler's seat/mic primitives."""

    def __init__(self, events, on_seat=False, mic_desc="开麦按钮", seat_succeeds=True,
                 mic_on_after_seat=None):
        self.events = events
        self.logger = _Logger()
        self.element_finder = _ElementFinder(events, mic_desc=mic_desc)
        self.on_seat = on_seat
        self.seat_succeeds = seat_succeeds
        self.mic_on_after_seat = mic_on_after_seat

    def is_on_seat(self):
        return self.on_seat

    def ensure_on_seat(self):
        self.events.append("ensure_on_seat")
        if not self.seat_succeeds:
            return False
        self.on_seat = True
        if self.mic_on_after_seat is not None:
            self.element_finder.mic_desc = "闭麦按钮" if self.mic_on_after_seat else "开麦按钮"
        return True


def _make_command(handler):
    controller = SimpleNamespace(soul_handler=handler, music_handler=SimpleNamespace())
    return MicCommand(controller)


def _run(command, parameters):
    import asyncio

    return asyncio.run(command.do_process(SimpleNamespace(nickname="Console"), parameters))


def _make_off_seat_command(**kwargs):
    events = []
    handler = _SoulHandler(events, on_seat=False, **kwargs)
    return _make_command(handler), handler, events


def test_mic_on_from_off_seat_takes_a_seat_before_opening_mic():
    command, _handler, events = _make_off_seat_command(mic_on_after_seat=False)

    result = _run(command, ["1"])

    assert events == ["ensure_on_seat", "click:toggle_mic"]
    assert result == {"state": "1"}


def test_mic_on_when_already_seated_does_not_take_a_seat():
    events = []
    handler = _SoulHandler(events, on_seat=True, mic_desc="开麦按钮")

    result = _run(_make_command(handler), ["1"])

    assert events == ["click:toggle_mic"]
    assert result == {"state": "1"}


def test_mic_off_never_touches_the_seat():
    command, _handler, events = _make_off_seat_command()

    result = _run(command, ["0"])

    assert events == []
    assert result == {"error": "Microphone is already off"}


def test_bare_mic_from_off_seat_opens_mic_instead_of_flipping_it_back_off():
    """Taking a seat turns the mic on, so the bare toggle must not mute it again."""
    command, _handler, events = _make_off_seat_command(mic_on_after_seat=True)

    result = _run(command, [])

    assert events == ["ensure_on_seat"]
    assert result == {"state": "1"}


def test_bare_mic_from_off_seat_clicks_toggle_when_mic_stays_muted():
    command, _handler, events = _make_off_seat_command(mic_on_after_seat=False)

    result = _run(command, [])

    assert events == ["ensure_on_seat", "click:toggle_mic"]
    assert result == {"state": "1"}


def test_mic_on_after_taking_a_seat_with_mic_already_open_reports_success():
    """Opening the mic right after seating is a success, not「already on」."""
    command, _handler, events = _make_off_seat_command(mic_on_after_seat=True)

    result = _run(command, ["1"])

    assert events == ["ensure_on_seat"]
    assert result == {"state": "1"}


def test_seat_failure_reports_error_and_leaves_mic_untouched():
    command, _handler, events = _make_off_seat_command(seat_succeeds=False)

    result = _run(command, ["1"])

    assert events == ["ensure_on_seat"]
    assert "error" in result
    assert "grab" in result["error"].lower()


def test_mic_on_reports_missing_toggle_button_when_seated():
    events = []
    handler = _SoulHandler(events, on_seat=True, mic_desc="开麦按钮")
    handler.element_finder.missing_toggle = True

    result = _run(_make_command(handler), ["1"])

    assert result == {"error": "Microphone button not found"}


def test_mic_on_when_already_open_still_reports_already_on_when_seated():
    events = []
    handler = _SoulHandler(events, on_seat=True, mic_desc="闭麦按钮")

    result = _run(_make_command(handler), ["1"])

    assert events == []
    assert result == {"error": "Microphone is already on"}
