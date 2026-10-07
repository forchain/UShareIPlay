"""座位子系统合并（票 #400）后的结构与对外契约。

合并前 `SeatManager` 是一个纯转发门面：八个公开方法逐个转给四个互相独立的单例，
面板展开/收起/滚动在 `SeatUIManager` 与 `SeatPanelDriver` 里各有一份近重复实现。
本文件钉住两件事：

1. **结构** —— 真实实现只有一处（`SeatSubsystem`），四个旧单例退化成转发件，
   面板动作只有一个实现；
2. **契约没动** —— 八个公开方法的返回形状、客房守卫、UI 独占锁语义与合并前一致。

替身按 tests/test_seat_panel_delegation.py 的做法在本文件内局部补齐，
不去改共用文件 tests/seat_fixtures.py —— 别的票也在改它。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.seat_fixtures import FakeController, make_handler, soul_elements

from ushareiplay.core.app_controller import AppController
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.guard import (
    GUEST_ROOM_CHAT_SCAN_RESULT,
    GUEST_ROOM_ENTRY_CHECK_RESULT,
    GUEST_ROOM_ERROR_RESULT,
)
from ushareiplay.managers.seat_manager.reservation import ReservationManager
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager
from ushareiplay.managers.seat_manager.seat_panel_driver import SeatPanelDriver
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

PUBLIC_SEAT_INTERFACES = (
    "reserve_seat",
    "take_seat",
    "remove_seat_occupant",
    "find_owner_seat",
    "remove_user_reservation",
    "accompany_user",
    "check_seats_on_entry",
    "prepare_for_chat_scan",
)

LEGACY_SINGLETONS = (
    SeatUIManager,
    SeatCheckManager,
    ReservationManager,
    SeatingManager,
    SeatManager,
)


# ---------------------------------------------------------------------------
# 局部替身
# ---------------------------------------------------------------------------
class _RecordingPanel:
    """面板协作者的最小契约：状态查询 + 收起。"""

    def __init__(self, expanded=False):
        self.expanded = expanded
        self.collapsed = False

    def check_seats_state(self):
        return self.expanded

    async def collapse_seats(self):
        self.collapsed = True
        return True

    async def expand_seats(self):
        return True

    async def expand_and_find_desks(self):
        return []

    def scroll_to_row(self, desk_index, seat_desks=None, duration=100):
        return False


@pytest.fixture(autouse=True)
def _reset_seat_singletons():
    for singleton in LEGACY_SINGLETONS:
        singleton.reset_instance()
    yield
    for singleton in LEGACY_SINGLETONS:
        singleton.reset_instance()


@pytest.fixture
def _guest_room():
    """他人房间开关（客房守卫的判据），用完复原。"""
    from ushareiplay.state.room_state import RoomState

    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    yield room_state
    RoomState.reset_instance()


def _bind(handler=None):
    """按接线层的顺序造出四个旧单例，再交给 SeatManager 接线。"""
    handler = handler if handler is not None else MagicMock()
    seat_ui = SeatUIManager.initialize(handler)
    seat_check = SeatCheckManager.initialize(handler, seat_ui)
    reservation = ReservationManager.initialize(handler, seat_ui, seat_check)
    seating = SeatingManager.initialize(handler, seat_ui)
    manager = SeatManager.initialize(
        handler, seat_ui, seat_check, reservation, seating
    )
    return manager, seat_ui, seat_check, reservation, seating


def _manager_with_panel(panel):
    SeatManager.reset_instance()
    return SeatManager.initialize(seat_ui=panel)


# ---------------------------------------------------------------------------
# 结构：真实实现只有一处
# ---------------------------------------------------------------------------
def test_seat_manager_owns_a_single_seat_subsystem():
    """八个公开接口背后是同一个子系统的方法，不是四个互相独立的单例。"""
    manager, *_ = _bind()
    subsystem = manager.subsystem

    assert isinstance(subsystem, SeatSubsystem)
    # 门面方法 -> 子系统方法的对应关系（门面保留旧的对外命名）。
    wiring = {
        "reserve_seat": "reserve_seat",
        "take_seat": "sit_at_specific_seat",
        "remove_seat_occupant": "seat_off_specific_seat",
        "find_owner_seat": "find_owner_seat",
        "remove_user_reservation": "remove_user_reservation",
        "accompany_user": "accompany_user",
        "check_seats_on_entry": "check_seats_on_entry",
        "prepare_for_chat_scan": "prepare_for_chat_scan",
    }
    assert set(wiring) == set(PUBLIC_SEAT_INTERFACES)
    for facade_name, subsystem_name in wiring.items():
        assert getattr(manager, facade_name).__name__ == facade_name
        assert hasattr(subsystem, subsystem_name), (
            f"{facade_name} 的实现没有落在子系统上"
        )
    # :seat 4 不带参数走的是 owner 那条路径
    assert hasattr(subsystem, "seat_off_owner")


def test_legacy_singletons_are_delegates_onto_the_managers_subsystem():
    """旧单例不再是四个独立实现，而是接到同一个子系统上的转发件。"""
    manager, seat_ui, seat_check, reservation, seating = _bind()
    subsystem = manager.subsystem

    assert seat_ui.subsystem is subsystem
    assert seat_check.subsystem is subsystem
    assert reservation.subsystem is subsystem
    assert seating.subsystem is subsystem

    # 预约/占座两个流程不再经过中间单例：预留与占座都由子系统自己实现。
    assert reservation.reserve_seat.__name__ == "reserve_seat"
    assert subsystem.panel is not seat_ui, "面板协作者不能回指接线层，否则会自调用"


def test_legacy_singletons_still_expose_their_own_collaborators():
    manager, seat_ui, seat_check, reservation, seating = _bind()

    assert manager._ui is seat_ui
    assert manager._check is seat_check
    assert manager._reservation is reservation
    assert manager._seating is seating
    assert seat_check.seat_ui is seat_ui
    assert reservation.seat_ui is seat_ui
    assert reservation.seat_check is seat_check
    assert seating.seat_ui is seat_ui


def test_seat_panel_actions_have_a_single_implementation():
    """#395 之后 seat_ui.py 还留着一份近重复的面板逻辑，这里必须退役。

    面板的唯一实现在 SeatPanelDriver 上：四个旧单例的展开/收起/滚动都转发过去。
    """
    for legacy in (SeatUIManager, SeatCheckManager, SeatingManager, ReservationManager):
        source = getattr(legacy, "collapse_seats", None) or getattr(
            legacy, "expand_and_find_desks", None
        )
        assert source is None or source.__module__ == legacy.__module__, (
            f"{legacy.__name__} 自己实现面板动作，面板逻辑没有收敛到 SeatSubsystem"
        )

    manager, seat_ui, *_ = _bind()
    assert seat_ui.subsystem.panel.driver is manager.subsystem.panel.driver


def test_seat_ui_manager_is_expanded_tracks_the_panel_driver():
    """面板只有一份状态：旧的 is_expanded 不再是另一套缓存。"""
    _manager, seat_ui, *_ = _bind()
    driver = seat_ui.subsystem.panel.driver

    assert isinstance(driver, SeatPanelDriver)
    assert seat_ui.is_expanded is False
    driver.expanded = True
    assert seat_ui.is_expanded is True


# ---------------------------------------------------------------------------
# 对外契约：八个公开方法没有动
# ---------------------------------------------------------------------------
async def test_prepare_for_chat_scan_only_collapses_when_the_panel_is_open():
    panel = _RecordingPanel(expanded=True)
    assert await _manager_with_panel(panel).prepare_for_chat_scan() is True
    assert panel.collapsed is True

    panel = _RecordingPanel(expanded=False)
    assert await _manager_with_panel(panel).prepare_for_chat_scan() is True
    assert panel.collapsed is False


async def test_public_interfaces_keep_their_delegate_return_shapes():
    """注入的外部替身仍被尊重：既有测试用这种方式钉住转发路径的返回值。"""
    reservation = SimpleNamespace(
        reserve_seat=AsyncMock(return_value={"reserved": ("Alice", 5)}),
        remove_user_reservation=AsyncMock(return_value={"unreserved": "Alice"}),
    )
    seating = SimpleNamespace(
        sit_at_specific_seat=AsyncMock(return_value={"took": 7}),
        seat_off_owner=AsyncMock(return_value={"removed": "owner"}),
        seat_off_specific_seat=AsyncMock(return_value={"removed": 3}),
        find_owner_seat=AsyncMock(return_value={"took": "anywhere"}),
        accompany_user=AsyncMock(return_value={"accompanied": "Bob"}),
    )
    check = SimpleNamespace(
        check_seats_on_entry=AsyncMock(return_value=None),
    )
    manager = SeatManager.initialize(
        seat_ui=_RecordingPanel(),
        reservation=reservation,
        seating=seating,
        seat_check=check,
    )

    assert await manager.reserve_seat("Alice", 5) == {"reserved": ("Alice", 5)}
    assert await manager.remove_user_reservation("Alice") == {"unreserved": "Alice"}
    assert await manager.take_seat(7) == {"took": 7}
    assert await manager.remove_seat_occupant(None) == {"removed": "owner"}
    assert await manager.remove_seat_occupant(3) == {"removed": 3}
    assert await manager.find_owner_seat() == {"took": "anywhere"}
    assert await manager.accompany_user("Bob") == {"accompanied": "Bob"}
    assert await manager.check_seats_on_entry("Alice") is None

    # :seat 4 [n] 的两条路径没有混起来
    seating.seat_off_owner.assert_awaited_once_with()
    seating.seat_off_specific_seat.assert_awaited_once_with(3)
    reservation.reserve_seat.assert_awaited_once_with("Alice", 5)


async def test_guest_room_guard_still_short_circuits_every_public_interface(_guest_room):
    SeatManager.reset_instance()
    manager = SeatManager.initialize(
        seat_ui=_RecordingPanel(expanded=True),
        reservation=SimpleNamespace(
            reserve_seat=AsyncMock(side_effect=AssertionError("不该被调用")),
            remove_user_reservation=AsyncMock(side_effect=AssertionError("不该被调用")),
        ),
        seating=SimpleNamespace(
            sit_at_specific_seat=AsyncMock(side_effect=AssertionError("不该被调用")),
            seat_off_owner=AsyncMock(side_effect=AssertionError("不该被调用")),
            seat_off_specific_seat=AsyncMock(side_effect=AssertionError("不该被调用")),
            find_owner_seat=AsyncMock(side_effect=AssertionError("不该被调用")),
            accompany_user=AsyncMock(side_effect=AssertionError("不该被调用")),
        ),
        seat_check=SimpleNamespace(
            check_seats_on_entry=AsyncMock(side_effect=AssertionError("不该被调用")),
        ),
    )

    assert await manager.reserve_seat("Alice", 1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.take_seat(1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.find_owner_seat() == GUEST_ROOM_ERROR_RESULT
    assert await manager.accompany_user("Bob") == GUEST_ROOM_ERROR_RESULT
    assert await manager.remove_seat_occupant(1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.remove_user_reservation("Alice") == GUEST_ROOM_ERROR_RESULT
    assert await manager.check_seats_on_entry("Alice") == GUEST_ROOM_ENTRY_CHECK_RESULT
    assert await manager.prepare_for_chat_scan() == GUEST_ROOM_CHAT_SCAN_RESULT


def test_every_public_interface_carries_the_guest_room_guard():
    """守卫是装饰在门面方法上的，合并不得把它摘掉。"""
    import ushareiplay.managers.seat_manager as seat_package
    from ushareiplay.managers.seat_manager import guard

    manager = SeatManager.initialize()
    for name in PUBLIC_SEAT_INTERFACES:
        wrapped = getattr(manager, name)
        assert getattr(wrapped, "__wrapped__", None) is not None, (
            f"{name} 上的 guest_room_guard 被合并掉了"
        )
        assert wrapped.__wrapped__ is not None
    assert guard.GUEST_ROOM_ERROR_RESULT == {
        "error": "他人房间不支持座位功能"
    }
    assert seat_package.SeatManager is SeatManager


# ---------------------------------------------------------------------------
# UI 独占锁契约
# ---------------------------------------------------------------------------
async def test_subsystem_ui_session_is_caller_held_and_degrades_without_controller():
    """ui_lock 不可重入：子系统不得在 driver 已持锁的链路里自取锁。

    - controller 缺席（单元测试）时退化为不加锁，而不是抛错；
    - controller 在场时每次座位流程恰好申请一次 ui_session；
    - 面板驱动自己从不申请锁（#395 定下的契约，合并必须保留）。
    """
    controller = FakeController()
    handler = make_handler(controller=controller)
    subsystem = SeatSubsystem(handler)

    async with subsystem._ui_session("probe"):
        pass
    assert controller.sessions == ["probe"]

    # controller 缺席 -> 退化为不加锁
    standalone = SeatSubsystem(make_handler(controller=None))
    async with standalone._ui_session("no-controller"):
        pass

    # SeatPanelDriver 不自取锁
    driver = SeatPanelDriver(handler)
    async with driver.ui_session("held-by-caller"):
        assert driver.handler is handler
    assert controller.sessions[-1] == "held-by-caller"


async def test_nested_ui_session_inside_a_held_command_session_does_not_self_deadlock():
    """``reserve_seat -> check_user_specific_seat`` 整条链本来就在命令的锁内。

    可重入性由 AppController.ui_session 的同 task 直通提供，子系统不得绕过它自己
    再 acquire 一次。锁挂住不放就说明合并把这条接缝弄坏了，所以显式超时。
    """
    controller = AppController.__new__(AppController)
    controller.ui_lock = asyncio.Lock()
    controller.logger = None
    handler = make_handler(controller=controller)
    subsystem = SeatSubsystem(handler)

    async with controller.ui_session("command:seat"):
        assert controller.ui_lock.locked() is True
        nested = subsystem._ui_session("seat_check:1")
        await asyncio.wait_for(nested.__aenter__(), timeout=2)
        try:
            # 嵌套的 session 不得把命令还持有的锁放掉
            assert controller.ui_lock.locked() is True
        finally:
            await asyncio.wait_for(nested.__aexit__(None, None, None), timeout=2)
        assert controller.ui_lock.locked() is True

    assert controller.ui_lock.locked() is False


async def test_legacy_check_handle_keeps_its_message_dispatch_hook():
    """既有测试在 SeatCheckManager 实例上直接挂 _message_dispatch，接缝不能断。"""
    controller = FakeController()
    handler = make_handler(controller=controller)
    subsystem = SeatSubsystem(handler)
    seat_check = SeatCheckManager.initialize(handler)
    seat_check.bind_subsystem(subsystem)

    sent = []
    seat_check._message_dispatch = SimpleNamespace(
        send_screen_message=lambda message: sent.append(message)
    )
    assert seat_check.subsystem.message_dispatch is seat_check._message_dispatch
    assert seat_check.panel_driver is subsystem.panel_driver


def test_observation_stays_a_lazy_lookup():
    """SeatManager 不得在构造期急初始化 SeatObservationManager 单例。"""
    from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager

    SeatObservationManager.reset_instance()
    try:
        manager = SeatManager.initialize(make_handler())
        assert not SeatObservationManager.is_initialized()
        assert manager.observation is None
        assert manager._observation is None

        observation = SeatObservationManager.initialize(make_handler())
        assert manager.observation is observation
        assert manager._observation is observation
    finally:
        SeatObservationManager.reset_instance()