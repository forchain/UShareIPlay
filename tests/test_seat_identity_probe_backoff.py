"""复现生产事故：占座但读不出昵称的麦位被每轮被动观测反复点头像（12:44-12:45 真机日志）。

真机现象（10-08 12:44:00 起，每 3~5 秒一轮，无限重复）：

    [ui_lock] acquired: seat_inspect
    Inspecting occupant on seat 11 (left side)
    wait_for_any_element: ['souler_name', 'user_name'] 超时未找到任何元素
    [ui_lock] released: seat_inspect

占座证据成立（ClState 等），但弹窗里读不出昵称节点 —— 这一位永远补不出身份。
_residual_seats 冷却只覆盖「已知是谁的残留渲染」，而「身份始终未知」的位子不在其中，
于是每轮观测都重新点头像弹窗，既刷屏又持续抢占 ui_lock。

修复后的契约：同一号位在 cooldown 内不得重复弹窗；冷却到期仍读不出才允许再试一次。
"""

import time

import pytest

from tests.seat_fixtures import build_live_desk_wrappers_for, make_handler
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatRescanCooldownPolicy,
)


@pytest.fixture(autouse=True)
def reset_observation():
    SeatObservationManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float):
        self.current += seconds


@pytest.mark.asyncio
async def test_unreadable_occupied_seat_is_not_reinspected_every_round():
    """身份始终读不出的占座位：一次弹窗失败后必须进入冷却，不得每轮重试。"""
    clock = FakeClock()
    handler = make_handler(popup_name=None)  # 弹窗开了但读不出昵称节点
    manager = SeatObservationManager.initialize(handler)
    manager.cooldown_policy = SeatRescanCooldownPolicy(
        residual_inspect_cooldown=60.0,
        time_fn=clock,
    )
    probe = _ProbeSpy(None)
    manager.inspect_occupant = probe

    # 11 号位：占座证据成立，昵称不在 DOM 里（普通用户形状）
    desks = build_live_desk_wrappers_for(handler, {11: True}, "bottom")

    for _ in range(5):
        await manager.observe_visible_desks(desks, current_focus_count=7)

    assert probe.count_for(11) == 1, (
        "占座但昵称始终读不出的麦位，只应弹窗一次；"
        f"实际弹了 {probe.count_for(11)} 次（每轮重复弹窗 = 生产死循环）"
    )

    # 冷却到期后允许再试一次（面板可能已经重绘/换人）
    clock.advance(61.0)
    await manager.observe_visible_desks(desks, current_focus_count=7)
    assert probe.count_for(11) == 2, "冷却到期后必须允许重新尝试"


@pytest.mark.asyncio
async def test_successful_identity_is_not_suppressed_by_probe_backoff():
    """读过一次的号位仍走快照沿用，绝不因为冷却机制退化成不弹窗。"""
    clock = FakeClock()
    handler = make_handler(popup_name="Bob")
    manager = SeatObservationManager.initialize(handler)
    manager.cooldown_policy = SeatRescanCooldownPolicy(
        residual_inspect_cooldown=60.0,
        time_fn=clock,
    )
    probe = _ProbeSpy("Bob")
    manager.inspect_occupant = probe

    desks = build_live_desk_wrappers_for(handler, {11: True}, "bottom")

    await manager.observe_visible_desks(desks, current_focus_count=7)

    assert probe.count_for(11) == 1
    assert manager.seats[11].username == "Bob"

    # 后续轮次靠快照沿用，不再弹窗
    for _ in range(3):
        await manager.observe_visible_desks(desks, current_focus_count=7)

    assert probe.count_for(11) == 1
    assert manager.seats[11].username == "Bob"


@pytest.mark.asyncio
async def test_probe_backoff_expires_when_seat_becomes_readable():
    """冷却期内位子换了人（label 直接给出昵称）应立刻生效，不被冷却挡住。"""
    clock = FakeClock()
    handler = make_handler(popup_name=None)
    manager = SeatObservationManager.initialize(handler)
    manager.cooldown_policy = SeatRescanCooldownPolicy(
        residual_inspect_cooldown=60.0,
        time_fn=clock,
    )
    probe = _ProbeSpy(None)
    manager.inspect_occupant = probe

    desks = build_live_desk_wrappers_for(handler, {11: True}, "bottom")
    await manager.observe_visible_desks(desks, current_focus_count=7)
    assert probe.count_for(11) == 1

    # 面板重绘：11 号位 label 直接渲染出昵称。
    # 10 号位必须占座，否则整条带位没有数字锚点，座位号读不出来（见 _map_desks_with_identity）。
    named_desks = build_live_desk_wrappers_for(handler, {11: "Carol", 10: True}, "bottom")
    await manager.observe_visible_desks(named_desks, current_focus_count=7)

    assert manager.seats[11].username == "Carol", "读得出昵称时绝不依赖弹窗，冷却不得挡住"
    assert probe.count_for(11) == 1


class _ProbeSpy:
    """inspect_occupant 的记录型替身：记住每个号位被弹了几次、每次读到什么。"""

    def __init__(self, result=None):
        self.result = result
        self.seat_calls = []

    async def __call__(self, _desk, side, seat_number):
        self.seat_calls.append((seat_number, side))
        return self.result

    def count_for(self, seat_number: int) -> int:
        return sum(1 for num, _side in self.seat_calls if num == seat_number)

    @property
    def total(self) -> int:
        return len(self.seat_calls)