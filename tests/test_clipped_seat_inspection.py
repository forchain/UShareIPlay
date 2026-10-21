"""测试视口中残片/未完整显示的桌位（如 12 号座仅露出几十像素）的安全交互门禁。

防止生产事故：
当派对面板处于收起状态或视口只露出部分后排残片时，Android 无障碍层仍会 dump 出
其子树中的占座特征节点（ClState 等）。原实现盲目对残片坐标发起 inspect_occupant，
点击落点偏离真实头像，导致 wait_for_any_element 每次等待 1.5s 超时并在 60s 冷却后
反复死循环报错。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from tests.seat_fixtures import make_handler, build_live_desk_wrapper, build_desk_wrapper
from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager


@pytest.fixture(autouse=True)
def reset_observation():
    SeatObservationManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()


def test_is_desk_interactable_predicates():
    """验证桌位有效交互高度判断。"""
    handler = make_handler()
    obs_manager = SeatObservationManager.initialize(handler)

    # 1. 完整桌位（真机 1080p 典型值：宽 309，高 207）
    full_desk = MagicMock()
    full_desk.bounds = {"x": 28, "y": 611, "width": 309, "height": 207}
    assert obs_manager._is_desk_interactable(full_desk) is True

    # 2. 底部裁剪残片（真机折叠/顶相位典型残片：高 45px 或 56px）
    clipped_45 = MagicMock()
    clipped_45.bounds = {"x": 383, "y": 845, "width": 309, "height": 45}
    assert obs_manager._is_desk_interactable(clipped_45) is False

    clipped_56 = MagicMock()
    clipped_56.bounds = {"x": 383, "y": 800, "width": 309, "height": 56}
    assert obs_manager._is_desk_interactable(clipped_56) is False

    # 3. 顶部裁剪残片（真机底相位典型残片：高 18px）
    clipped_18 = MagicMock()
    clipped_18.bounds = {"x": 28, "y": 566, "width": 309, "height": 18}
    assert obs_manager._is_desk_interactable(clipped_18) is False

    # 4. 无有效 bounds（单测 mock 替身放行，不阻断单测）
    no_bounds = MagicMock()
    no_bounds.bounds = None
    no_bounds.location = None
    no_bounds.size = None
    assert obs_manager._is_desk_interactable(no_bounds) is True


@pytest.mark.asyncio
async def test_clipped_seat_should_not_be_inspected_blindly():
    """视口中未完整显示的座位残片（如 12 号座只露出几十像素），不应被盲目调用 inspect_occupant 点击头像。"""
    handler = make_handler(popup_name=None)
    manager = SeatObservationManager.initialize(handler)

    # 前两张桌位完全可见（高度 207px），且有数字锚点
    d2 = build_live_desk_wrapper(handler, left=(5, True, None), right=(6, False, None), y=611, bounds="[28,611][337,818]")
    d3 = build_live_desk_wrapper(handler, left=(7, True, None), right=(8, False, None), y=611, bounds="[383,611][692,818]")

    # 第三张桌位（11/12 号座）在视口底部被裁剪，高度仅 45px，12 号座被检测为占座
    d5 = build_live_desk_wrapper(handler, left=(11, False, None), right=(12, True, None), y=845, bounds="[383,845][692,890]")

    inspected_seats = []
    original_inspect = manager.inspect_occupant

    async def tracking_inspect(desk, side, seat_num):
        inspected_seats.append((seat_num, side, desk.bounds))
        return await original_inspect(desk, side, seat_num)

    manager.inspect_occupant = tracking_inspect

    await manager.observe_visible_desks([d2, d3, d5])

    # 断言：被视口裁剪、未完整显示的 12 号座绝不被调用 inspect_occupant 点头像
    assert 12 not in [s[0] for s in inspected_seats], (
        f"未完全显示的 12 号座位（残片高度 45px）不应被调用 inspect_occupant，"
        f"实际却被调用了: {inspected_seats}"
    )
    # 完整可见的 5 号与 7 号正常探索
    assert 5 in [s[0] for s in inspected_seats]
    assert 7 in [s[0] for s in inspected_seats]


@pytest.mark.asyncio
async def test_click_seat_avatar_refuses_clipped_desk():
    """_click_seat_avatar 对高度不足的残片桌位直接返回 False，绝不向 Appium 发送无效点击。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 残片桌位
    d5 = build_live_desk_wrapper(handler, left=(11, False, None), right=(12, True, None), y=845, bounds="[383,845][692,890]")
    target = manager._find_child_element(d5, "right_state")

    assert manager._click_seat_avatar(d5, "right", target) is False
    # gesture_handler 未被触发点击
    handler.gesture_handler.click_at.assert_not_called()


@pytest.mark.asyncio
async def test_inspect_occupant_on_clipped_desk_returns_none_without_waiting():
    """inspect_occupant 面对残片桌位直接早退返回 None，不调用 wait_for_any_element，不产生超时报错。"""
    handler = make_handler(popup_name="AnyName")
    manager = SeatObservationManager.initialize(handler)

    d5 = build_live_desk_wrapper(handler, left=(11, False, None), right=(12, True, None), y=845, bounds="[383,845][692,890]")
    result = await manager.inspect_occupant(d5, "right", 12)

    assert result is None
    # 绝不调用 wait_for_any_element 进行无谓的 1.5s 超时等待
    assert handler.element_finder.wait_calls == 0
    # 绝不盲目按返回键
    handler.key_actions.press_back.assert_not_called()

