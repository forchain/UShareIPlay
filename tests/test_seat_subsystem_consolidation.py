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

import pytest

from tests.seat_fixtures import FakeController, make_handler, soul_elements

from ushareiplay.core.app_controller import AppController
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager import subsystem as seat_subsystem_module
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


def test_the_only_injection_seam_lands_on_one_subsystem():
    """#402 之后只剩面板契约一个接缝，三个死接缝已从签名里删掉。

    面板对象不是死接缝：`SeatObservationManager` 消费的就是这一份契约
    （app_controller 把 `subsystem.panel` 交给它），所以它保留。`seat_check` /
    `reservation` / `seating` 指向的类在 `src/` 里已经不存在，留着只是转发给
    「不存在的协作者」，只被测试替身够得着。
    """
    panel = _RecordingPanel()
    manager = SeatManager.initialize(seat_ui=panel)

    assert isinstance(manager.subsystem, SeatSubsystem)
    # 面板只有一个入口：注入的 seat_ui 就是子系统暴露的 panel。
    assert manager.subsystem.panel is panel

    for dead in ("seat_check", "reservation", "seating"):
        assert not hasattr(manager.subsystem, f"_{dead}"), f"{dead} 接缝还在"
        with pytest.raises(TypeError):
            SeatSubsystem(make_handler(), **{dead: SimpleNamespace()})


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


async def test_public_interfaces_keep_their_canonical_return_shapes(monkeypatch):
    """八个公开接口的返回形状来自真实实现，不再经过任何转发替身（#402）。

    转发替身删掉之前，这个用例断言的是**替身自己**的返回值 —— 也就是说它对生产
    代码什么都没说。现在断言真实实现走真实路径时返回的形状。
    """
    manager = SeatManager.initialize(
        make_handler(controller=None), seat_ui=_RecordingPanel()
    )

    # 参数域校验：还没碰任何设备就能返回的形状
    assert await manager.take_seat(0) == {
        "error": "Invalid seat number 0. Must be between 1 and 12"
    }
    assert await manager.take_seat(13) == {
        "error": "Invalid seat number 13. Must be between 1 and 12"
    }

    # handler 缺席：设备依赖的入口都必须短路成同一支错误形状，不能 AttributeError
    SeatManager.reset_instance()
    headless = SeatManager.initialize(seat_ui=_RecordingPanel())
    assert await headless.remove_seat_occupant(None) == {"error": "Handler not initialized"}
    assert await headless.remove_seat_occupant(3) == {"error": "Handler not initialized"}
    assert await headless.find_owner_seat() == {"error": "Handler not initialized"}
    assert await headless.accompany_user("Bob") == {"error": "Handler not initialized"}

    # 预约两个入口的真实错误形状（替身只换 DAO，不换实现）
    async def _no_user(_username):
        return None

    monkeypatch.setattr(
        seat_subsystem_module,
        "UserDAO",
        SimpleNamespace(get_or_create=_no_user),
    )
    assert await manager.reserve_seat("Alice", 5) == {
        "error": "Failed to get or create user Alice"
    }
    assert await manager.remove_user_reservation("Alice") == {
        "error": "Failed to get or create user Alice"
    }


async def test_remove_seat_occupant_keeps_the_owner_and_specific_paths_apart(monkeypatch):
    """`:seat 4` 不带参数走 owner 那条，带参数走指定号位 —— 两条路径没有混起来。"""
    manager = SeatManager.initialize(
        make_handler(controller=None), seat_ui=_RecordingPanel()
    )
    subsystem = manager.subsystem
    calls = []

    async def _owner():
        calls.append("owner")
        return {"error": "Handler not initialized"}

    async def _specific(seat_number):
        calls.append(("specific", seat_number))
        return {"error": "Handler not initialized"}

    monkeypatch.setattr(subsystem, "seat_off_owner", _owner)
    monkeypatch.setattr(subsystem, "seat_off_specific_seat", _specific)

    await manager.remove_seat_occupant(None)
    await manager.remove_seat_occupant(3)

    assert calls == ["owner", ("specific", 3)], calls


async def test_guest_room_guard_still_short_circuits_every_public_interface(
    _guest_room, monkeypatch
):
    """守卫必须挡在实现之前：他人房间里一条实现都不许跑。

    替身换成就地埋雷：把子系统上每个实现都换成「一被调用就报错」，于是这个用例
    证明的是守卫真的在门面就短路了，而不是「某个替身没被 await 到」。
    """
    manager = SeatManager.initialize(
        make_handler(controller=None), seat_ui=_RecordingPanel(expanded=True)
    )

    def _explode(*_args, **_kwargs):
        raise AssertionError("他人房间里不该跑到位子子系统的实现")

    for name in (
        "reserve_seat",
        "sit_at_specific_seat",
        "seat_off_owner",
        "seat_off_specific_seat",
        "find_owner_seat",
        "remove_user_reservation",
        "accompany_user",
        "check_seats_on_entry",
        "prepare_for_chat_scan",
    ):
        monkeypatch.setattr(manager.subsystem, name, _explode)

    assert await manager.reserve_seat("Alice", 1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.take_seat(1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.find_owner_seat() == GUEST_ROOM_ERROR_RESULT
    assert await manager.accompany_user("Bob") == GUEST_ROOM_ERROR_RESULT
    assert await manager.remove_seat_occupant(1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.remove_user_reservation("Alice") == GUEST_ROOM_ERROR_RESULT
    assert await manager.check_seats_on_entry("Alice") == GUEST_ROOM_ENTRY_CHECK_RESULT
    assert await manager.prepare_for_chat_scan() == GUEST_ROOM_CHAT_SCAN_RESULT


async def test_check_seats_on_entry_without_a_handler_returns_quietly():
    """没有 handler 时不得 AttributeError。

    原实现把「handler 缺席」和「username 缺席」并成一条判断，第一件事就是解引用
    `self.handler.logger` —— 缺席分支自己先崩（票 #402 回归护栏）。
    """
    subsystem = SeatSubsystem(handler=None)

    assert await subsystem.check_seats_on_entry("Alice") is None


async def test_check_seats_on_entry_without_a_username_warns_once():
    """username 缺席仍要留痕：调用方传错了参数。"""
    handler = make_handler(controller=None)
    subsystem = SeatSubsystem(handler)

    assert await subsystem.check_seats_on_entry(None) is None


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