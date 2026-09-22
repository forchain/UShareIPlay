import asyncio
from types import SimpleNamespace

from ushareiplay.events.risk_elements import RiskElementsEvent, __elements__


class FakeLogger:
    def __init__(self):
        self.debugs = []
        self.infos = []
        self.warnings = []
        self.errors = []

    def debug(self, msg):
        self.debugs.append(msg)

    def info(self, msg):
        self.infos.append(msg)

    def warning(self, msg):
        self.warnings.append(msg)

    def error(self, msg):
        self.errors.append(msg)


class FakeElement:
    def __init__(self):
        self.clicked = False

    def click(self):
        self.clicked = True


class FakeFinder:
    def __init__(self, element=None):
        self.element = element

    def wait_for_element_clickable(self, key):
        return self.element


class FakeHandler:
    def __init__(self, element=None):
        self.logger = FakeLogger()
        self.controller = None
        self.element_finder = FakeFinder(element)


def test_collapse_seats_is_in_risk_elements():
    """collapse_seats is monitored to ensure seat panel does not obstruct chat area when idle."""
    assert "collapse_seats" in __elements__


def test_risk_elements_skips_when_ui_busy():
    element = FakeElement()
    handler = FakeHandler(element)
    runtime = SimpleNamespace(is_ui_busy=lambda: True)

    event = RiskElementsEvent(handler, runtime=runtime)
    result = asyncio.run(event.handle("claim_reward_button", None))

    assert result is False
    assert element.clicked is False
    assert any("UI is busy" in msg for msg in handler.logger.debugs)


def test_collapse_seats_skips_when_ui_busy():
    """Crucial fix: collapse_seats must NOT be clicked when a probe or command is active."""
    element = FakeElement()
    handler = FakeHandler(element)
    runtime = SimpleNamespace(is_ui_busy=lambda: True)

    event = RiskElementsEvent(handler, runtime=runtime)
    result = asyncio.run(event.handle("collapse_seats", None))

    assert result is False
    assert element.clicked is False
    assert any("UI is busy" in msg for msg in handler.logger.debugs)


def test_risk_elements_clicks_when_ui_idle():
    element = FakeElement()
    handler = FakeHandler(element)
    runtime = SimpleNamespace(is_ui_busy=lambda: False)

    event = RiskElementsEvent(handler, runtime=runtime)
    result = asyncio.run(event.handle("claim_reward_button", None))

    assert result is True
    assert element.clicked is True
    assert any("Processed risk element" in msg for msg in handler.logger.infos)


def test_collapse_seats_collapses_via_seat_ui_when_idle(monkeypatch):
    """When idle, collapse_seats delegates to SeatUIManager to properly collapse seats."""
    from ushareiplay.managers.seat_manager import SeatManager

    collapsed = False

    class FakeSeatUI:
        async def collapse_seats(self):
            nonlocal collapsed
            collapsed = True
            return True

    fake_seat_manager = SimpleNamespace(_ui=FakeSeatUI())
    monkeypatch.setattr(SeatManager, "is_initialized", lambda: True)
    monkeypatch.setattr(SeatManager, "get_instance", lambda: fake_seat_manager)

    element = FakeElement()
    handler = FakeHandler(element)
    runtime = SimpleNamespace(is_ui_busy=lambda: False)

    event = RiskElementsEvent(handler, runtime=runtime)
    result = asyncio.run(event.handle("collapse_seats", None))

    assert result is True
    assert collapsed is True
    # Should not click raw element since seat_ui handled it
    assert element.clicked is False
