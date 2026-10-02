import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from selenium.common.exceptions import StaleElementReferenceException

from ushareiplay.core.app_controller import AppController
from ushareiplay.core.runtime_context import EventRuntimeContext
from ushareiplay.managers.seat_manager import seat_check as seat_check_module
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager


class DummyHandler:
    def __init__(self, desks):
        self.logger = SimpleNamespace(
            info=lambda message: None,
            warning=lambda message: None,
            error=lambda message: None,
        )
        self.desks = desks
        self.searched_desks = []
        self.errors = []
        self.swipes = []
        self.driver = SimpleNamespace(swipe=lambda *args: self.swipes.append(args))

    def find_elements(self, key):
        assert key == "seat_desk"
        return self.desks

    def log_error(self, message):
        self.errors.append(message)

    def send_message(self, message):
        pass

    def find_child_element(self, parent, key):
        if key == "left_seat":
            self.searched_desks.append(parent)
            return object()
        return None

    @property
    def element_finder(self):
        return self


class DummySeatUI:
    def __init__(self, handler):
        self.handler = handler

    async def expand_and_find_desks(self):
        seat_desks = self.handler.element_finder.find_elements("seat_desk")
        if len(seat_desks) != 6:
            self.handler.log_error(
                f"seat expansion incomplete: found {len(seat_desks)} desks, expected 6"
            )
            return None
        return seat_desks

    def scroll_to_row(self, desk_index, seat_desks, duration=100):
        row_index = desk_index // 2
        if row_index not in (0, 2):
            return
        reference_desk = seat_desks[2]
        center_x = reference_desk.location["x"] + reference_desk.size["width"] // 2
        center_y = reference_desk.location["y"] + reference_desk.size["height"] // 2
        offset = reference_desk.size["height"] if row_index == 0 else -reference_desk.size["height"]
        self.handler.driver.swipe(center_x, center_y, center_x, center_y + offset, duration)


def _desk():
    return SimpleNamespace(
        size={"height": 10, "width": 10},
        location={"x": 0, "y": 0},
    )


def _manager(handler):
    SeatCheckManager.reset_instance()
    return SeatCheckManager.initialize(handler, DummySeatUI(handler))


def test_check_user_specific_seat_stops_when_expansion_shows_four_desks():
    handler = DummyHandler([_desk() for _ in range(4)])
    manager = _manager(handler)
    asyncio.run(manager.check_user_specific_seat("Chainer", 9))

    assert handler.searched_desks == []
    assert handler.errors == ["seat expansion incomplete: found 4 desks, expected 6"]


def test_check_user_specific_seat_uses_global_index_when_all_desks_are_visible(monkeypatch):
    seat_desks = [_desk() for _ in range(6)]
    handler = DummyHandler(seat_desks)
    manager = _manager(handler)
    sleep = AsyncMock()
    monkeypatch.setattr(seat_check_module.asyncio, "sleep", sleep)
    asyncio.run(manager.check_user_specific_seat("Chainer", 9))

    assert handler.swipes == [(5, 5, 5, -5, 1000)]
    assert handler.searched_desks == [seat_desks[4]]
    sleep.assert_awaited_once_with(0.5)


# ---------------------------------------------------------------------------
# Seat avatar-card flow vs. EventManager's unknown-page fallback back
# ---------------------------------------------------------------------------


class _FakeDom:
    """Stand-in for the Soul page while the seat avatar card is open.

    ``press_back`` dismisses the card, so every element handle previously taken
    out of it goes stale — the same way Android drops the popup's views.
    """

    def __init__(self):
        self.card_attached = True
        self.fallback_suppressed = False
        self.fallback_pressed_back = False
        self.seat_off_clicked = False


class _CardElement:
    """Element handle into the avatar card; only ``seat_off`` can go stale."""

    def __init__(self, dom, kind, text=None):
        self.dom = dom
        self.kind = kind
        self._text = text

    @property
    def text(self):
        return self._text

    def click(self):
        if self.kind == "seat_off":
            if not self.dom.card_attached:
                raise StaleElementReferenceException(
                    "Message: The element 'By.id: cn.soulapp.android:id/tvSeatDownUp' "
                    "does not exist in DOM anymore"
                )
            self.dom.seat_off_clicked = True


class _CardHandler(DummyHandler):
    """DummyHandler extended with the popup reads/writes of the occupied-seat flow."""

    OCCUPANT = "Bob"

    def __init__(self, desks, dom):
        super().__init__(desks)
        self.dom = dom
        self.controller = None
        self.key_actions = self

    # -- avatar card open/close -------------------------------------------
    def press_back(self):
        self.dom.card_attached = False
        self.dom.fallback_pressed_back = True

    # -- element_finder surface used by SeatCheckManager --------------------
    def find_child_element(self, parent, key):
        if key == "left_seat":
            return _CardElement(self.dom, "seat_avatar")
        if key == "left_label":
            return _CardElement(self.dom, "label", text=self.OCCUPANT)
        return None

    def wait_for_element_clickable(self, key, timeout=10):
        assert key == "seat_off"
        return _CardElement(self.dom, "seat_off")

    def wait_for_any_element(self, keys, timeout=10):
        return "souler_name", _CardElement(self.dom, "souler_name", text=self.OCCUPANT)


def _user(level):
    return SimpleNamespace(level=level)


@pytest.mark.asyncio
async def test_occupied_seat_flow_survives_event_manager_fallback_back(monkeypatch):
    """The seat avatar card must not be dismissed mid-flow by the unknown-page back.

    Repro of the production race: ``seat_off`` (``tvSeatDownUp``) is located,
    then two ``await`` points (the UserDAO level lookups) yield to the event
    loop. EventManager's unknown-page recovery presses back whenever the UI is
    not held by ``AppController.ui_lock``, which tears the card down and leaves
    the retained handle stale — the click then dies with
    ``StaleElementReferenceException`` and the seat is never cleared.
    """
    dom = _FakeDom()
    handler = _CardHandler([_desk() for _ in range(6)], dom)

    controller = AppController.__new__(AppController)
    controller.ui_lock = asyncio.Lock()
    controller.logger = None  # ui_session only logs when a logger is attached
    handler.controller = controller
    event_runtime = EventRuntimeContext(ui_lock=controller.ui_lock)

    async def fallback_back():
        """Replica of EventManager.react_to_page's recovery branch.

        See ``EventManager.react_to_page``: an unknown page is only auto-exited
        when ``is_ui_busy()`` is False; otherwise the back is suppressed.
        """
        if event_runtime.is_ui_busy():
            dom.fallback_suppressed = True
            return
        handler.press_back()

    fired = False

    async def get_by_username(username):
        # First level lookup happens after the card is open but before the
        # seat_off click: exactly the window the production log shows.
        nonlocal fired
        if not fired:
            fired = True
            await fallback_back()
        return _user(5 if username == "Chainer" else 3)

    monkeypatch.setattr(seat_check_module, "UserDAO", SimpleNamespace(get_by_username=get_by_username))
    monkeypatch.setattr(seat_check_module.asyncio, "sleep", AsyncMock())

    manager = _manager(handler)
    manager._message_dispatch = SimpleNamespace(send_screen_message=lambda *a, **k: None)

    await manager.check_user_specific_seat("Chainer", 1)

    assert dom.fallback_suppressed is True, "unknown-page back ran while the seat flow owned the UI"
    assert dom.fallback_pressed_back is False
    assert dom.seat_off_clicked is True
    assert handler.errors == []


@pytest.mark.asyncio
async def test_seat_check_flow_does_not_deadlock_inside_a_held_command_session(monkeypatch):
    """A ``:seat`` command already owns ui_lock when it reaches the seat check.

    ``CommandManager`` wraps every command dispatch in ``ui_session``, and
    ``reserve_seat`` calls straight into ``check_user_specific_seat``.
    ``asyncio.Lock`` is not reentrant, so acquiring it again there would hang
    command dispatch forever rather than fail — hence the explicit timeout.
    """
    dom = _FakeDom()
    handler = _CardHandler([_desk() for _ in range(6)], dom)

    controller = AppController.__new__(AppController)
    controller.ui_lock = asyncio.Lock()
    controller.logger = None
    handler.controller = controller

    async def get_by_username(username):
        return _user(5 if username == "Chainer" else 3)

    monkeypatch.setattr(seat_check_module, "UserDAO", SimpleNamespace(get_by_username=get_by_username))
    monkeypatch.setattr(seat_check_module.asyncio, "sleep", AsyncMock())

    manager = _manager(handler)
    manager._message_dispatch = SimpleNamespace(send_screen_message=lambda *a, **k: None)

    async with controller.ui_session("command:seat"):
        assert controller.ui_lock.locked() is True
        await asyncio.wait_for(manager.check_user_specific_seat("Chainer", 1), timeout=2)
        # the nested session must not release the lock the command is still holding
        assert controller.ui_lock.locked() is True

    assert controller.ui_lock.locked() is False
    assert dom.seat_off_clicked is True
    assert handler.errors == []
