"""Ticket #306: fast-path targeting and fallback for the accompany command."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.seat_panel import make_panel

from ushareiplay.commands import seat as seat_command_module
from ushareiplay.commands.seat import SeatCommand
from ushareiplay.core.roles import DEFAULT_ROOM_OWNER
from ushareiplay.managers.seat_manager.roster import UNKNOWN_USERNAME, SeatRoster
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.state.room_state import RoomState


class _StubInfoManager:
    """Stands in for the online-presence lookup."""

    def __init__(self):
        self.online = True

    def is_user_online(self, username):
        return self.online


@pytest.fixture(autouse=True)
def _dependencies(monkeypatch):
    monkeypatch.setattr(SeatUIManager, "EXPANSION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(SeatUIManager, "COLLAPSE_SETTLE_SECONDS", 0)
    info_manager = _StubInfoManager()
    monkeypatch.setattr(
        seating_module(), "InfoManager", SimpleNamespace(instance=lambda: info_manager)
    )
    if not RoomState.is_initialized():
        RoomState.initialize()
    room_state = RoomState.instance()
    room_state.is_guest_room = False
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    return info_manager


def seating_module():
    from ushareiplay.managers.seat_manager import seating

    return seating


def _stack(panel, focus_count=None):
    roster = SeatRoster()
    ui = SeatUIManager(panel.handler)
    from ushareiplay.managers.seat_manager.probe import SeatProbe

    probe = SeatProbe(
        panel.handler, ui, roster, focus_count_provider=lambda: focus_count
    )
    ui.bind_probe(probe)
    seating = SeatingManager(panel.handler, ui, probe=probe)
    return ui, probe, roster, seating


def _primed(panel, focus_count=None):
    ui, probe, roster, seating = _stack(panel, focus_count)
    asyncio.run(ui.expand_and_find_desks())
    panel.popup_clicks = 0
    panel.press_backs = 0
    panel.scrolls.clear()
    return ui, probe, roster, seating


def test_accompany_uses_the_cached_seat_with_a_single_verification_popup():
    panel, _desks = make_panel({3: "Alice"})
    _ui, _probe, roster, seating = _primed(panel)

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"success": "Successfully took a seat"}
    assert panel.popup_clicks == 1
    assert roster.find_seat_of(DEFAULT_ROOM_OWNER) == 4


def test_accompany_sits_on_the_left_when_the_target_sits_on_the_right():
    panel, desks = make_panel({4: "Alice"})
    _ui, _probe, roster, seating = _primed(panel)

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"success": "Successfully took a seat"}
    assert desks[1].left_seat.clicked == 1
    assert roster.find_seat_of(DEFAULT_ROOM_OWNER) == 3


def test_fast_path_updates_the_host_position_in_the_roster():
    panel, _desks = make_panel({3: "Alice"})
    _ui, _probe, roster, seating = _primed(panel)

    asyncio.run(seating.accompany_user("Alice"))

    assert roster.occupant(4).username == DEFAULT_ROOM_OWNER
    assert roster.occupant(4).is_owner is True
    assert roster.is_occupied(4) is True


def test_cold_roster_is_probed_before_sitting_down():
    panel, _desks = make_panel({3: "Alice"})
    _ui, _probe, roster, seating = _stack(panel)

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"success": "Successfully took a seat"}
    # One popup to populate the roster, one to verify the target before sitting.
    assert panel.popup_clicks == 2
    assert roster.find_seat_of(DEFAULT_ROOM_OWNER) == 4


def test_a_changed_seat_triggers_the_differential_probe():
    panel, desks = make_panel({3: "Alice"})
    _ui, probe, roster, seating = _primed(panel)

    panel.clear_seat(3)
    panel.set_occupant(3, "Carol")
    panel.set_occupant(9, "Alice")

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"success": "Successfully took a seat"}
    assert roster.find_seat_of("Alice") == 9
    assert roster.find_seat_of(DEFAULT_ROOM_OWNER) == 10
    assert desks[4].right_seat.clicked == 1

    # Carol took the seat Alice left, so that seat is occupied but unidentified:
    # the roster must not keep calling it Alice, nor hand it to Carol unread.
    assert roster.occupant(3) is None
    assert roster.occupancy_mask[2] is True

    # Being unidentified is a visible state, not a permanent one: the next sync
    # reads the seat again and finds Carol.
    asyncio.run(probe.sync(desks))

    assert roster.find_seat_of("Carol") == 3
    assert roster.find_seat_of("Alice") == 9


def test_a_seat_taken_over_without_an_occupancy_change_is_re_probed():
    panel, _desks = make_panel({3: "Alice"})
    _ui, _probe, roster, seating = _primed(panel)

    # Same seat stays occupied, so the occupancy mask sees nothing; only the
    # verification popup can reveal that the occupant changed.
    panel.clear_seat(3)
    panel.set_occupant(3, "Carol")

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"error": "User Alice not found on any seat"}
    assert roster.find_seat_of("Carol") == 3
    assert roster.find_seat_of("Alice") is None


def test_unidentified_target_reports_not_found():
    panel, _desks = make_panel({3: "Alice"})
    _ui, _probe, roster, seating = _primed(panel)

    result = asyncio.run(seating.accompany_user("Zoe"))

    assert result == {"error": "User Zoe not found on any seat"}
    assert panel.popup_clicks == 0


def test_a_target_without_an_empty_neighbour_is_rejected():
    panel, _desks = make_panel({3: "Alice", 4: "Bob"})
    _ui, _probe, roster, seating = _primed(panel)

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"error": "User Alice has no empty adjacent seat"}
    assert roster.find_seat_of(DEFAULT_ROOM_OWNER) is None


def test_a_target_without_an_empty_neighbour_is_rejected_on_any_desk():
    panel, _desks = make_panel({5: "Alice", 6: "Bob"})
    _ui, _probe, _roster, seating = _primed(panel)

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"error": "User Alice has no empty adjacent seat"}


def test_an_offline_target_is_rejected_without_touching_the_panel(_dependencies):
    panel, _desks = make_panel({3: "Alice"})
    _ui, _probe, _roster, seating = _stack(panel)
    _dependencies.online = False

    result = asyncio.run(seating.accompany_user("Alice", sender_username="Bob"))

    assert result == {"error": "User Alice is not online"}
    assert panel.expand_clicks == 0
    assert panel.popup_clicks == 0


def test_the_sender_is_never_checked_for_being_online(_dependencies):
    panel, _desks = make_panel({3: "Alice"})
    _ui, _probe, _roster, seating = _primed(panel)
    _dependencies.online = False

    result = asyncio.run(seating.accompany_user("Alice", sender_username="Alice"))

    assert result == {"success": "Successfully took a seat"}


def test_a_neighbour_taken_mid_interaction_is_never_clicked():
    """The fresh desk read is authoritative, not the roster check before it."""
    panel, desks = make_panel({3: "Alice"})
    _ui, _probe, _roster, seating = _primed(panel)

    def squatter(_seat_number):
        panel.on_popup = None
        panel.set_occupant(4, "Squatter")

    panel.on_popup = squatter

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"error": "User Alice has no empty adjacent seat"}
    assert desks[1].right_seat.clicked == 0


def test_a_target_whose_popup_never_renders_is_not_matched():
    panel, _desks = make_panel({3: "Alice"}, popup_failures=[3])
    _ui, _probe, roster, seating = _primed(panel)

    result = asyncio.run(seating.accompany_user("Alice"))

    assert result == {"error": "User Alice not found on any seat"}
    assert roster.occupant(3).username == UNKNOWN_USERNAME


# --- command seam -------------------------------------------------------


def _command(monkeypatch, result=None):
    manager = SimpleNamespace(
        accompany_user=AsyncMock(return_value=result or {"success": "ok"})
    )
    monkeypatch.setattr(seat_command_module.SeatManager, "get_instance", lambda: manager)
    return SeatCommand(SimpleNamespace(soul_handler=SimpleNamespace(log_error=lambda _m: None), music_handler=None)), manager


def test_seat_3_without_a_parameter_accompanies_the_sender(monkeypatch):
    command, manager = _command(monkeypatch)
    message = MessageInfo(content=":seat 3", nickname="Alice")

    asyncio.run(command.process(message, ["3"]))

    manager.accompany_user.assert_awaited_once_with("Alice", sender_username="Alice")


def test_seat_3_with_a_target_accompanies_that_target(monkeypatch):
    command, manager = _command(monkeypatch)
    message = MessageInfo(content=":seat 3 Chainer", nickname="Alice")

    asyncio.run(command.process(message, ["3", "Chainer"]))

    manager.accompany_user.assert_awaited_once_with("Chainer", sender_username="Alice")
