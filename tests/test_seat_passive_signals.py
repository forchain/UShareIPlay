"""Ticket #307: passive room signals wired into the event system."""

from types import SimpleNamespace

import pytest
from lxml import etree

from ushareiplay.core.element_wrapper import ElementWrapper
from ushareiplay.events.focus_count import FocusCountEvent
from ushareiplay.events.seat_desk import SeatDeskEvent
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.state.room_state import RoomState

SEAT_DESK_ID = "cn.soulapp.android:id/userRoot"
LEFT_STATE_ID = "cn.soulapp.android:id/leftClState"
RIGHT_STATE_ID = "cn.soulapp.android:id/rightClState"

ELEMENTS = {
    "seat_desk": SEAT_DESK_ID,
    "left_state": LEFT_STATE_ID,
    "right_state": RIGHT_STATE_ID,
}


class RecordingWatcher:
    def __init__(self):
        self.masks = []
        self.focus_counts = []

    def note_occupancy_mask(self, mask):
        self.masks.append(tuple(mask))
        return True

    def note_focus_count(self, focus_count):
        self.focus_counts.append(focus_count)
        return True


@pytest.fixture(autouse=True)
def _room_state():
    """The conftest resets every singleton; RoomState is not part of that set."""
    if not RoomState.is_initialized():
        RoomState.initialize()
    RoomState.instance()._logger = SimpleNamespace(info=lambda _msg: None)
    yield RoomState.instance()


def _install_watcher(monkeypatch, watcher):
    """Make SeatManager.get_instance() hand out a manager owning ``watcher``."""
    monkeypatch.setattr(
        SeatManager,
        "get_instance",
        lambda *args, **kwargs: SimpleNamespace(get_watcher=lambda: watcher),
    )
    return watcher


def _handler(*, config=None, logger=None):
    return SimpleNamespace(
        config={"elements": ELEMENTS} if config is None else config,
        logger=logger
        or SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
            debug=lambda *_a, **_k: None,
        ),
        controller=None,
    )


def _page(*desks):
    """``desks`` is a sequence of ``(left_occupied, right_occupied)`` pairs."""
    containers = []
    for left, right in desks:
        children = []
        if left:
            children.append(f'<TextView resource-id="{LEFT_STATE_ID}"/>')
        if right:
            children.append(f'<TextView resource-id="{RIGHT_STATE_ID}"/>')
        containers.append(
            f'<FrameLayout resource-id="{SEAT_DESK_ID}">{"".join(children)}</FrameLayout>'
        )
    return etree.fromstring(f"<hierarchy>{''.join(containers)}</hierarchy>".encode())


def _desks(handler, *desk_states):
    root = _page(*desk_states)
    return [
        ElementWrapper(element, handler, "seat_desk")
        for element in root.xpath(f"//*[@resource-id='{SEAT_DESK_ID}']")
    ]


def _mask(*occupied_seats, desks_count=None):
    if desks_count is not None:
        visible_limit = desks_count * 2
        return tuple(
            (seat in occupied_seats) if seat <= visible_limit else None
            for seat in range(1, 13)
        )
    return tuple(seat in occupied_seats for seat in range(1, 13))


# --- collapsed viewport occupancy mask ---------------------------------


async def test_the_seat_desk_event_reports_the_visible_occupancy_mask(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())

    await SeatDeskEvent(handler).handle(
        "seat_desk", _desks(handler, (True, False), (False, True))
    )

    assert watcher.masks == [_mask(1, 4, desks_count=2)]


async def test_the_seat_desk_event_reports_an_empty_panel(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())

    await SeatDeskEvent(handler).handle("seat_desk", _desks(handler, (False, False)))

    assert watcher.masks == [_mask(desks_count=1)]


async def test_the_seat_desk_event_accepts_a_single_container(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())
    desks = _desks(handler, (False, True))

    await SeatDeskEvent(handler).handle("seat_desk", desks[0])

    assert watcher.masks == [_mask(2, desks_count=1)]


async def test_the_seat_desk_event_reads_seats_behind_the_six_container_limit(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())

    await SeatDeskEvent(handler).handle(
        "seat_desk", _desks(handler, *[(False, False)] * 7)
    )

    # A seventh container would be seat 13, which does not exist.
    assert watcher.masks == [_mask(desks_count=6)]


async def test_the_seat_desk_event_ignores_empty_containers(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())

    assert await SeatDeskEvent(handler).handle("seat_desk", []) is False
    assert await SeatDeskEvent(handler).handle("seat_desk", None) is False
    assert watcher.masks == []


async def test_the_seat_desk_event_is_harmless_without_a_watcher(monkeypatch):
    _install_watcher(monkeypatch, None)
    handler = _handler()

    result = await SeatDeskEvent(handler).handle(
        "seat_desk", _desks(handler, (True, True))
    )

    assert result is False


async def test_the_seat_desk_event_never_interrupts_event_processing(monkeypatch):
    handler = _handler()
    _install_watcher(monkeypatch, RecordingWatcher())

    result = await SeatDeskEvent(handler).handle(
        "seat_desk", _desks(handler, (True, False))
    )

    assert result is False


async def test_the_seat_desk_event_survives_a_malformed_container(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())
    broken = ElementWrapper(object(), handler, "seat_desk")

    result = await SeatDeskEvent(handler).handle("seat_desk", [broken])

    assert result is False
    assert watcher.masks == [_mask(desks_count=1)]


async def test_the_seat_desk_event_is_harmless_when_the_seat_manager_is_unavailable(
    monkeypatch,
):
    def exploding_get_instance(*args, **kwargs):
        raise RuntimeError("SeatManager is not bootstrapped")

    monkeypatch.setattr(SeatManager, "get_instance", exploding_get_instance)
    handler = _handler()

    result = await SeatDeskEvent(handler).handle(
        "seat_desk", _desks(handler, (True, False))
    )

    assert result is False


def test_the_seat_desk_module_registers_itself_for_the_seat_desk_element():
    import ushareiplay.events.seat_desk as module

    assert module.__elements__ == ["seat_desk"]
    assert module.__multiple__ is True
    assert hasattr(module, "SeatDeskEvent")


def test_the_seat_desk_event_reads_the_soul_scoped_element_table():
    from ushareiplay.events.seat_desk import _elements

    soul_scoped = SimpleNamespace(config={"soul": {"elements": ELEMENTS}})
    root_scoped = SimpleNamespace(config={"soul": {"elements": ELEMENTS}})
    root_scoped.controller = SimpleNamespace(config={"elements": {"unrelated": "x"}})

    assert _elements(soul_scoped) == ELEMENTS
    assert _elements(root_scoped) == ELEMENTS
    assert _elements(SimpleNamespace(config={}, controller=None)) == {}


# --- focus count --------------------------------------------------------


async def test_a_focus_count_change_signals_the_seat_watcher(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())

    await FocusCountEvent(handler).handle(
        "focus_count", SimpleNamespace(text="5人专注中")
    )

    assert watcher.focus_counts == [5]


async def test_an_unchanged_focus_count_is_not_signalled_again(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())
    event = FocusCountEvent(handler)

    await event.handle("focus_count", SimpleNamespace(text="5人专注中"))
    await event.handle("focus_count", SimpleNamespace(text="5人专注中"))

    assert watcher.focus_counts == [5]


async def test_an_unparseable_focus_count_is_not_signalled(monkeypatch):
    handler = _handler()
    watcher = _install_watcher(monkeypatch, RecordingWatcher())

    await FocusCountEvent(handler).handle(
        "focus_count", SimpleNamespace(text="暂无数据")
    )

    assert watcher.focus_counts == []


async def test_a_focus_count_change_without_a_watcher_is_harmless(monkeypatch):
    _install_watcher(monkeypatch, None)
    handler = _handler()

    result = await FocusCountEvent(handler).handle(
        "focus_count", SimpleNamespace(text="3人专注中")
    )

    assert result is False


async def test_a_focus_count_change_survives_an_unavailable_seat_manager(monkeypatch):
    """A seat-management failure must never break focus-count processing."""

    def exploding_get_instance(*args, **kwargs):
        raise RuntimeError("SeatManager is not bootstrapped")

    monkeypatch.setattr(SeatManager, "get_instance", exploding_get_instance)
    handler = _handler()

    result = await FocusCountEvent(handler).handle(
        "focus_count", SimpleNamespace(text="3人专注中")
    )

    assert result is False


# --- room changes -------------------------------------------------------


async def test_moving_to_another_room_drops_the_seat_roster(monkeypatch, _room_state):
    from ushareiplay.events.room_id import RoomIdEvent
    from ushareiplay.managers.seat_manager.roster import SeatRoster

    roster = SeatRoster()
    roster.set_occupant(3, "Alice")
    monkeypatch.setattr(SeatManager, "is_initialized", classmethod(lambda cls: True))
    monkeypatch.setattr(
        SeatManager,
        "get_instance",
        lambda *args, **kwargs: SimpleNamespace(get_roster=lambda: roster),
    )
    # Seat identities belong to a room; a persisted expectation would divert the
    # event into the leave-and-recreate path instead.
    _room_state._expected_party_id = None
    _room_state.room_id = "FM11111111"

    result = await RoomIdEvent(_handler()).handle(
        "room_id", SimpleNamespace(text="FM22222222")
    )

    assert result is False
    assert roster.occupants() == []


async def test_staying_in_the_same_room_keeps_the_seat_roster(monkeypatch, _room_state):
    from ushareiplay.events.room_id import RoomIdEvent
    from ushareiplay.managers.seat_manager.roster import SeatRoster

    roster = SeatRoster()
    roster.set_occupant(3, "Alice")
    monkeypatch.setattr(SeatManager, "is_initialized", classmethod(lambda cls: True))
    monkeypatch.setattr(
        SeatManager,
        "get_instance",
        lambda *args, **kwargs: SimpleNamespace(get_roster=lambda: roster),
    )
    _room_state._expected_party_id = None
    _room_state.room_id = "FM11111111"

    await RoomIdEvent(_handler()).handle("room_id", SimpleNamespace(text="FM11111111"))

    assert roster.find_seat_of("Alice") == 3
