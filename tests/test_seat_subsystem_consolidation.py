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
from tests.seat_support import build_seat_service

from ushareiplay.adapters.outbound.appium.soul.seat_panel_driver import SeatPanelDriver
from ushareiplay.core.app_controller import AppController
from ushareiplay.modules.seat.domain import (
    GUEST_ROOM_CHAT_SCAN_RESULT,
    GUEST_ROOM_EMPTY_DESK_RESULT,
    GUEST_ROOM_ENTRY_CHECK_RESULT,
    GUEST_ROOM_ERROR_RESULT,
)
from ushareiplay.modules.seat.use_cases import SeatService

PUBLIC_SEAT_INTERFACES = (
    "reserve_seat",
    "take_seat",
    "remove_seat_occupant",
    "find_owner_seat",
    "remove_user_reservation",
    "accompany_user",
    "check_seats_on_entry",
    "prepare_for_chat_scan",
    "invite_user_to_seat",
    "find_verified_isolated_empty_desk",
    "chat_scan_session",
)

# #402 之后座位子系统只剩门面这一个单例；`SeatObservationManager` 是另一个单例，
# 由它自己的测试负责。
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


@pytest.fixture
def _guest_room():
    """他人房间开关（客房守卫的判据），用完复原。"""
    from tests.legacy_state import RoomState

    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    yield room_state
    RoomState.reset_instance()


def _manager_with_panel(panel):
    return build_seat_service(seat_ui=panel)


# ---------------------------------------------------------------------------
# 结构：真实实现只有一处（SeatService）
# ---------------------------------------------------------------------------
def test_seat_manager_owns_a_single_seat_subsystem():
    """十个受守卫的公开接口全部落在 SeatService 上。"""
    service = build_seat_service()

    assert isinstance(service, SeatService)
    for name in PUBLIC_SEAT_INTERFACES:
        assert hasattr(service, name), f"{name} 缺失"
    assert hasattr(service, "seat_off_owner")


def test_the_subsystem_owns_the_reservation_and_seating_flows():
    """预约/占座两个流程由 SeatService 自己实现。"""
    service = build_seat_service()

    assert service.reserve_seat.__name__ == "reserve_seat"
    assert service.sit_at_specific_seat.__name__ == "sit_at_specific_seat"
    assert service.check_seats_on_entry.__name__ == "check_seats_on_entry"

    panel = _RecordingPanel()
    assert build_seat_service(seat_ui=panel)._panel._seat_ui is panel


def test_the_only_injection_seam_lands_on_one_subsystem():
    """面板入口只有一个：注入的 seat_ui 落在 _panel._seat_ui 上，死接缝已移除。"""
    panel = _RecordingPanel()
    service = build_seat_service(seat_ui=panel)

    assert isinstance(service, SeatService)
    assert service._panel._seat_ui is panel

    for dead in ("seat_check", "reservation", "seating"):
        assert not hasattr(service, f"_{dead}"), f"{dead} 接缝还在"
        with pytest.raises(TypeError):
            SeatService(make_handler(), **{dead: SimpleNamespace()})


def test_seat_panel_actions_have_a_single_implementation():
    """面板动作只有一个实现：SeatPanelDriver。"""
    service = build_seat_service()

    assert isinstance(service._panel, SeatPanelDriver)


def test_panel_expanded_state_tracks_the_driver():
    """面板只有一份状态：is_expanded 直接读驱动，不是另一套缓存。"""
    service = build_seat_service()
    driver = service._panel

    assert isinstance(driver, SeatPanelDriver)
    assert driver.is_expanded() is False
    driver.expanded = True
    assert driver.expanded is True


# ---------------------------------------------------------------------------
# 对外契约：公开方法没有动
# ---------------------------------------------------------------------------
async def test_prepare_for_chat_scan_only_collapses_when_the_panel_is_open():
    panel = _RecordingPanel(expanded=True)
    assert await _manager_with_panel(panel).prepare_for_chat_scan() is True
    assert panel.collapsed is True

    panel = _RecordingPanel(expanded=False)
    assert await _manager_with_panel(panel).prepare_for_chat_scan() is True
    assert panel.collapsed is False


async def test_prepare_for_chat_scan_leaves_the_panel_alone_while_the_ui_lock_is_held():
    """持锁的流程拥有座位面板：锁被持有时聊天扫描不许把面板收起。

    真机 10-23 11:42:52：座位流程 `seat_auto_invite` 持有 ui_lock 展开面板，
    聊天回溯把面板收起 —— 座位带视口从 513px 缩回 290px，RecyclerView 回收第三排，
    桌位从 6 张掉回 4 张，`expand_and_find_desks` 报 "found 4 desks, expected 6"。
    """
    controller = FakeController()
    panel = _RecordingPanel(expanded=True)
    manager = build_seat_service(
        make_handler(controller=controller),
        seat_ui=panel,
        lease=controller.ui_session_lease,
    )

    acquired = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with controller.ui_session("seat_auto_invite:someone"):
            acquired.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await acquired.wait()
    try:
        assert await manager.prepare_for_chat_scan() is True
        assert panel.collapsed is False
    finally:
        release.set()
        await task


async def test_public_interfaces_keep_their_canonical_return_shapes(monkeypatch):
    """公开接口的返回形状来自真实实现，不再经过任何转发替身（#402）。

    转发替身删掉之前，这个用例断言的是**替身自己**的返回值 —— 也就是说它对生产
    代码什么都没说。现在断言真实实现走真实路径时返回的形状。
    """
    manager = build_seat_service(
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
    headless = build_seat_service(seat_ui=_RecordingPanel())
    assert await headless.remove_seat_occupant(None) == {"error": "Handler not initialized"}
    assert await headless.remove_seat_occupant(3) == {"error": "Handler not initialized"}
    assert await headless.find_owner_seat() == {"error": "Handler not initialized"}
    assert await headless.accompany_user("Bob") == {"error": "Handler not initialized"}

    # 预约两个入口的真实错误形状（替身只换 DAO，不换实现）
    async def _no_user(_username):
        return None

    manager._users = SimpleNamespace(get_or_create=_no_user)
    assert await manager.reserve_seat("Alice", 5) == {
        "error": "Failed to get or create user Alice"
    }
    assert await manager.remove_user_reservation("Alice") == {
        "error": "Failed to get or create user Alice"
    }


async def test_remove_seat_occupant_keeps_the_owner_and_specific_paths_apart(monkeypatch):
    """`:seat 4` 不带参数走 owner 那条，带参数走指定号位 —— 两条路径没有混起来。"""
    manager = build_seat_service(
        make_handler(controller=None), seat_ui=_RecordingPanel()
    )
    subsystem = manager
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
    manager = build_seat_service(
        make_handler(controller=None), seat_ui=_RecordingPanel(expanded=True)
    )

    def _explode(*_args, **_kwargs):
        raise AssertionError("他人房间里不该跑到位子子系统的实现")

    # 守卫与实现在同一个方法上：能替换的是公开入口背后的内部实现。
    for name in (
        "sit_at_specific_seat",
        "seat_off_owner",
        "seat_off_specific_seat",
        "_prepare_empty_seat_click",
        "_find_verified_isolated_empty_desk",
    ):
        monkeypatch.setattr(manager, name, _explode)

    assert await manager.reserve_seat("Alice", 1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.take_seat(1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.find_owner_seat() == GUEST_ROOM_ERROR_RESULT
    assert await manager.accompany_user("Bob") == GUEST_ROOM_ERROR_RESULT
    assert await manager.remove_seat_occupant(1) == GUEST_ROOM_ERROR_RESULT
    assert await manager.remove_seat_occupant(None) == GUEST_ROOM_ERROR_RESULT
    assert await manager.remove_user_reservation("Alice") == GUEST_ROOM_ERROR_RESULT
    assert await manager.check_seats_on_entry("Alice") == GUEST_ROOM_ENTRY_CHECK_RESULT
    assert await manager.prepare_for_chat_scan() == GUEST_ROOM_CHAT_SCAN_RESULT
    assert await manager.invite_user_to_seat(1, "Bob") == GUEST_ROOM_ERROR_RESULT
    assert await manager.find_verified_isolated_empty_desk() == GUEST_ROOM_EMPTY_DESK_RESULT
    # 补漏会话在他人房间直接放行，不碰座位 UI
    async with manager.chat_scan_session():
        pass


async def test_check_seats_on_entry_without_a_handler_returns_quietly():
    """没有 handler 时不得 AttributeError。

    原实现把「handler 缺席」和「username 缺席」并成一条判断，第一件事就是解引用
    `self.handler.logger` —— 缺席分支自己先崩（票 #402 回归护栏）。
    """
    service = build_seat_service(handler=None)

    assert await service.check_seats_on_entry("Alice") is None


async def test_check_seats_on_entry_without_a_username_warns_once():
    """username 缺席仍要留痕：调用方传错了参数。"""
    handler = make_handler(controller=None)
    service = build_seat_service(handler)

    assert await service.check_seats_on_entry(None) is None


def test_every_public_interface_carries_the_guest_room_guard():
    """守卫是装饰在用例方法上的，迁移不得把它摘掉。"""
    from ushareiplay.modules.seat import domain as seat_domain

    service = build_seat_service()
    for name in PUBLIC_SEAT_INTERFACES:
        if name == "chat_scan_session":
            continue
        wrapped = getattr(service, name)
        assert getattr(wrapped, "__wrapped__", None) is not None, (
            f"{name} 上的 guest_room_guard 被摘掉了"
        )
    assert seat_domain.GUEST_ROOM_ERROR_RESULT == {
        "error": "他人房间不支持座位功能"
    }


# ---------------------------------------------------------------------------
# UI 独占锁契约
# ---------------------------------------------------------------------------
async def test_subsystem_ui_session_is_caller_held_and_degrades_without_controller():
    controller = FakeController()
    handler = make_handler(controller=controller)
    service = build_seat_service(handler, lease=controller.ui_session_lease)

    async with service._ui_session("probe"):
        pass
    assert controller.sessions == ["probe"]

    standalone = build_seat_service(make_handler(controller=None))
    async with standalone._ui_session("no-controller"):
        pass

    driver = SeatPanelDriver(handler, lease=controller.ui_session_lease)
    async with driver.ui_session("held-by-caller"):
        assert driver.handler is handler
    assert controller.sessions[-1] == "held-by-caller"


async def test_nested_ui_session_inside_a_held_command_session_does_not_self_deadlock():
    controller = AppController.__new__(AppController)
    controller.ui_lock = asyncio.Lock()
    controller.logger = None
    handler = make_handler(controller=controller)
    service = build_seat_service(handler, lease=controller.ui_session_lease)

    async with controller.ui_session("command:seat"):
        assert controller.ui_lock.locked() is True
        nested = service._ui_session("seat_check:1")
        await asyncio.wait_for(nested.__aenter__(), timeout=2)
        try:
            assert controller.ui_lock.locked() is True
        finally:
            await asyncio.wait_for(nested.__aexit__(None, None, None), timeout=2)
        assert controller.ui_lock.locked() is True

    assert controller.ui_lock.locked() is False