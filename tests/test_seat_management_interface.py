import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

from ushareiplay.managers.seat_manager import SeatManager


class _FakeSeatUI:
    def __init__(self, expanded):
        self.expanded = expanded
        self.collapsed = False

    def check_seats_state(self):
        return self.expanded

    async def collapse_seats(self):
        self.collapsed = True
        return True


class _FakeReservation:
    async def reserve_seat(self, username, seat_number):
        return {"reserved": (username, seat_number)}


class _FakeSeating:
    async def sit_at_specific_seat(self, seat_number):
        return {"took": seat_number}

    async def seat_off_owner(self):
        return {"removed": "owner"}

    async def seat_off_specific_seat(self, seat_number):
        return {"removed": seat_number}


@pytest.fixture(autouse=True)
def _cleanup_seat_manager():
    SeatManager.reset_instance()
    yield
    SeatManager.reset_instance()


def _manager_with_fakes(ui=None, reservation=None, seating=None):
    SeatManager.reset_instance()
    manager = SeatManager.initialize(
        seat_ui=ui or _FakeSeatUI(expanded=False),
        reservation=reservation or _FakeReservation(),
        seating=seating or _FakeSeating(),
    )
    return manager


@pytest.mark.asyncio
async def test_prepare_for_chat_scan_collapses_only_when_seats_are_expanded():
    expanded_ui = _FakeSeatUI(expanded=True)
    collapsed_ui = _FakeSeatUI(expanded=False)

    assert await _manager_with_fakes(ui=expanded_ui).prepare_for_chat_scan() is True
    assert expanded_ui.collapsed is True

    assert await _manager_with_fakes(ui=collapsed_ui).prepare_for_chat_scan() is True
    assert collapsed_ui.collapsed is False


@pytest.mark.asyncio
async def test_seat_management_delegates_reserve_and_take_intentions():
    manager = _manager_with_fakes()

    assert await manager.reserve_seat("Alice", 5) == {"reserved": ("Alice", 5)}
    assert await manager.take_seat(7) == {"took": 7}


@pytest.mark.asyncio
async def test_seat_management_preserves_remove_occupant_paths():
    manager = _manager_with_fakes()

    assert await manager.remove_seat_occupant(None) == {"removed": "owner"}
    assert await manager.remove_seat_occupant(3) == {"removed": 3}


def test_seat_manager_wires_every_injected_collaborator_onto_one_subsystem():
    """面板只有 `subsystem.panel` 一个入口（#402 之后不再有第二个面板对象）。

    #402 之前这里断言五个单例对象互相引用同一个 `seat_ui`；四个内部单例删掉后，
    活下来的等价命题是：显式注入的 `seat_ui` **就是**子系统暴露的面板入口，
    因此「共享同一份面板依赖」这件事对调用方仍然成立且可断言。
    预约/占座两个注入点的委托形状由上面两个测试钉住。
    """
    handler = object()
    seat_ui = _FakeSeatUI(expanded=False)
    manager = SeatManager.initialize(
        handler,
        seat_ui=seat_ui,
        reservation=_FakeReservation(),
        seating=_FakeSeating(),
    )

    assert manager.subsystem.panel is seat_ui


@pytest.mark.asyncio
async def test_message_manager_prepares_chat_scan_through_seat_management(monkeypatch):
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSeatManagement:
        def __init__(self):
            self.prepared = False

        async def prepare_for_chat_scan(self):
            self.prepared = True
            return True

    seat_management = _FakeSeatManagement()
    manager = MessageManager.instance()
    manager._handler = SimpleNamespace(
        logger=SimpleNamespace(error=lambda message: None, critical=lambda message: None),
    )
    manager._handler.key_actions = SimpleNamespace(switch_to_app=lambda: True)
    manager._chat_logger = None

    monkeypatch.setattr(
        MessageManager,
        "_get_seat_manager",
        lambda self: seat_management,
    )

    assert await manager.process_missed_messages() is None
    assert seat_management.prepared is True
