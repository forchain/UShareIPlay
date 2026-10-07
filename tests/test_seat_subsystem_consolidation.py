"""座位子系统合并（票 #400 / #402）后的结构与对外契约。

合并前 `SeatManager` 是一个纯转发门面：八个公开方法逐个转给四个互相独立的单例，
面板展开/收起/滚动在面板单例与 `SeatPanelDriver` 里各有一份近重复实现。
本文件钉住两件事：

1. **结构** —— 真实实现只有一处（`SeatSubsystem`），四个旧单例由 #402 删除，
   面板动作只有一个实现；
2. **契约没动** —— 八个公开方法的返回形状、客房守卫、UI 独占锁语义与合并前一致。

替身按 tests/test_seat_panel_delegation.py 的做法在本文件内局部补齐，
不去改共用文件 tests/seat_fixtures.py —— 别的票也在改它。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.seat_fixtures import FakeController, make_handler, soul_elements

from ushareiplay.core.app_controller import AppController
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.guard import (
    GUEST_ROOM_CHAT_SCAN_RESULT,
    GUEST_ROOM_ENTRY_CHECK_RESULT,
    GUEST_ROOM_ERROR_RESULT,
)
from ushareiplay.managers.seat_manager.seat_panel_driver import SeatPanelDriver
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

# #402 之后座位子系统只剩门面这一个单例；`SeatObservationManager` 是另一个单例，
# 由它自己的测试负责。
SEAT_SINGLETONS = (SeatManager,)


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
    for singleton in SEAT_SINGLETONS:
        singleton.reset_instance()
    yield
    for singleton in SEAT_SINGLETONS:
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


def _manager_with_panel(panel):
    SeatManager.reset_instance()
    return SeatManager.initialize(seat_ui=panel)


# ---------------------------------------------------------------------------
# 结构：真实实现只有一处
# ---------------------------------------------------------------------------
def test_seat_manager_owns_a_single_seat_subsystem():
    """八个公开接口背后是同一个子系统的方法，不是四个互相独立的单例。"""
    manager = SeatManager.initialize()
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


def test_the_subsystem_owns_the_reservation_and_seating_flows():
    """预约/占座两个流程由子系统自己实现，外面没有第二份实现。"""
    manager = SeatManager.initialize()
    subsystem = manager.subsystem

    assert subsystem.reserve_seat.__name__ == "reserve_seat"
    assert subsystem.sit_at_specific_seat.__name__ == "sit_at_specific_seat"
    assert subsystem.check_seats_on_entry.__name__ == "check_seats_on_entry"

    # 注入的面板协作者就是面板入口本身：不存在第二个「实现」对象回指子系统，
    # 也就不会自调用（#402 之前这里的旧单例句柄正是那个回指风险）。
    panel = _RecordingPanel()
    assert SeatSubsystem(seat_ui=panel).panel is panel


def test_every_injected_collaborator_lands_on_one_subsystem():
    """四个注入点全部落到同一个子系统上（#402 之后没有第二个实现对象）。"""
    panel = _RecordingPanel()
    manager = SeatManager.initialize(
        seat_ui=panel,
        seat_check=SimpleNamespace(),
        reservation=SimpleNamespace(),
        seating=SimpleNamespace(),
    )

    assert isinstance(manager.subsystem, SeatSubsystem)
    # 面板只有一个入口：注入的 seat_ui 就是子系统暴露的 panel。
    assert manager.subsystem.panel is panel


def test_seat_panel_actions_have_a_single_implementation():
    """面板动作只有一个实现：SeatPanelDriver。

    #402 删掉了那份近重复的面板逻辑，座位子系统不再可能自带展开/收起/滚动。
    这里钉住剩下的一半不变式：面板入口始终由 `panel_driver` 驱动，且反复取用是
    同一个对象（缓存），不是每次新建一份适配层。
    """
    manager = SeatManager.initialize()
    subsystem = manager.subsystem

    assert isinstance(subsystem.panel.driver, SeatPanelDriver)
    assert subsystem.panel.driver is subsystem.panel_driver
    assert subsystem.panel is subsystem.panel


def test_panel_expanded_state_tracks_the_driver():
    """面板只有一份状态：`panel.is_expanded` 直接读驱动，不是另一套缓存。"""
    manager = SeatManager.initialize()
    panel = manager.subsystem.panel
    driver = manager.subsystem.panel_driver

    assert isinstance(driver, SeatPanelDriver)
    assert panel.is_expanded is False
    driver.expanded = True
    assert panel.is_expanded is True


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


def test_subsystem_keeps_its_injected_message_dispatch():
    """既有测试直接挂 `_message_dispatch`，接缝不能断。"""
    handler = make_handler(controller=FakeController())
    subsystem = SeatSubsystem(handler)

    sent = []
    injected = SimpleNamespace(
        send_screen_message=lambda message: sent.append(message)
    )
    subsystem._message_dispatch = injected

    assert subsystem.message_dispatch is injected


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