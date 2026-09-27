"""
Ticket #346: Targeted seating (:seat 2 <n>) with viewport sync pipeline.

Tests:
1. Direct row navigation with scroll phase propagation (band="top" / "bottom") without sequential scanning.
2. Snapshot update and abort without clicking when target seat is occupied in post-scroll page_source.
3. Coordinate bounds click and confirm seating when empty, followed by snapshot and focus count updates.
4. Clean panel collapse on completion or error.
5. Suppression of downstream focus count rescan (+1 count).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lxml import etree

from tests.seat_fixtures import (
    SEAT_DOM_FIXTURES,
    FakeElementFinder,
    FakeSeatUI,
    make_handler,
)
from ushareiplay.core.element_wrapper import ElementWrapper
from ushareiplay.events.focus_count import FocusCountEvent
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def reset_state():
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    RoomState._instance = None
    yield
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    RoomState._instance = None


def _load_xml(filename: str) -> str:
    return (SEAT_DOM_FIXTURES / filename).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_sit_at_specific_seat_navigates_directly_to_target_row_and_collapses():
    """目标麦位导航直达目标排，传播对应相位，且最终收起面板。"""
    handler = make_handler()
    top_xml = _load_xml("expanded_top_with_anchor.xml")
    bottom_xml = _load_xml("expanded_scrolled_bottom.xml")

    handler.driver = MagicMock()
    handler.driver.page_source = bottom_xml

    observation = SeatObservationManager.initialize(handler)

    # 构造 FakeSeatUI，记录滚动行
    fake_seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager(handler=handler, seat_ui=fake_seat_ui, observation=observation)

    # Mock 确认弹窗
    confirm_elem = MagicMock()
    handler.element_finder.wait_for_element_clickable = MagicMock(
        side_effect=lambda key, **kwargs: confirm_elem if key == "confirm_seat" else None
    )

    # 目标为 9 号位（第 3 排，desk 4）
    result = await seating.sit_at_specific_seat(9)

    assert result.get("success") is not None
    # 确认直接滚动到 row 2（第 3 排），没有顺序扫描 row 0, 1
    assert fake_seat_ui.scrolled_rows == [2]
    # 确认面板已收起
    assert fake_seat_ui.collapsed is True


@pytest.mark.asyncio
async def test_sit_at_specific_seat_aborts_without_clicking_when_seat_is_occupied():
    """若目标麦位在滚动后 page_source 中已占用，更新快照并直接返回错误，不执行点击。"""
    handler = make_handler()
    top_xml = _load_xml("expanded_top_with_anchor.xml")  # 1 号位为群主占用

    handler.driver = MagicMock()
    handler.driver.page_source = top_xml

    observation = SeatObservationManager.initialize(handler)
    fake_seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager(handler=handler, seat_ui=fake_seat_ui, observation=observation)

    # 尝试入座 1 号位（已占用）
    result = await seating.sit_at_specific_seat(1)

    assert "error" in result
    assert "occupied" in result["error"].lower() or "已占用" in result["error"] or "1" in result["error"]

    # 严禁触发任何坐标物理点击
    handler.gesture_handler.click_at.assert_not_called()

    # 快照已同步为已占用
    assert observation.seats[1].occupied is True
    assert observation.seats[1].is_owner is True

    # 失败后面板仍必须收起
    assert fake_seat_ui.collapsed is True


@pytest.mark.asyncio
async def test_sit_at_specific_seat_clicks_coordinate_bounds_and_confirms_when_empty():
    """目标麦位为空闲时，根据 page_source 导出的坐标点击并确认就座，同步快照与基准。"""
    handler = make_handler()
    top_xml = _load_xml("expanded_top_with_anchor.xml")  # 2 号位为空闲（点击入座）

    handler.driver = MagicMock()
    handler.driver.page_source = top_xml

    observation = SeatObservationManager.initialize(handler)
    observation._last_focus_count = 1

    fake_seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager(handler=handler, seat_ui=fake_seat_ui, observation=observation)

    # Mock 确认弹窗
    confirm_elem = MagicMock()
    handler.element_finder.wait_for_element_clickable = MagicMock(
        side_effect=lambda key, **kwargs: confirm_elem if key == "confirm_seat" else None
    )

    result = await seating.sit_at_specific_seat(2)

    assert result.get("success") is not None
    # 确认调用了坐标点击 gesture_handler.click_at
    handler.gesture_handler.click_at.assert_called_once()
    click_x, click_y = handler.gesture_handler.click_at.call_args.args
    # 检查坐标处于 2 号位 bounds 范围内（desk 0 右座 bounds=[170,576][305,743]）
    assert 170 <= click_x <= 305
    assert 576 <= click_y <= 743

    # 确认弹窗被点击
    confirm_elem.click.assert_called_once()

    # 快照被标记为群主占用
    assert observation.seats[2].occupied is True
    assert observation.seats[2].is_owner is True
    assert observation.seats[2].username == "群主"

    # 基准与已对账人数递增（1 -> 2）
    assert observation._last_focus_count == 2
    assert observation._reconciled_focus_count == 2

    # 面板收起
    assert fake_seat_ui.collapsed is True


@pytest.mark.asyncio
async def test_sit_at_specific_seat_collapses_panel_on_error():
    """发生异常时，finally 仍会安全收起座位面板。"""
    handler = make_handler()
    handler.driver = MagicMock()
    handler.driver.page_source = _load_xml("expanded_top_with_anchor.xml")

    observation = SeatObservationManager.initialize(handler)
    fake_seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager(handler=handler, seat_ui=fake_seat_ui, observation=observation)

    # 模拟确认就座异常
    handler.element_finder.wait_for_element_clickable = MagicMock(side_effect=RuntimeError("UI error"))

    result = await seating.sit_at_specific_seat(2)
    assert "error" in result
    assert fake_seat_ui.collapsed is True


@pytest.mark.asyncio
async def test_subsequent_focus_count_event_does_not_trigger_full_rescan():
    """就座成功后，下游专注人数 +1 事件不再触发背离全量重扫。"""
    handler = make_handler()
    top_xml = _load_xml("expanded_top_with_anchor.xml")
    handler.driver = MagicMock()
    handler.driver.page_source = top_xml

    observation = SeatObservationManager.initialize(handler)
    observation._last_focus_count = 1

    fake_seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager(handler=handler, seat_ui=fake_seat_ui, observation=observation)

    confirm_elem = MagicMock()
    handler.element_finder.wait_for_element_clickable = MagicMock(
        side_effect=lambda key, **kwargs: confirm_elem if key == "confirm_seat" else None
    )

    # 就座 2 号位
    await seating.sit_at_specific_seat(2)
    assert observation._last_focus_count == 2
    assert observation._reconciled_focus_count == 2

    # 模拟 FocusCountEvent 处理 “2人专注中”
    event = FocusCountEvent(handler)
    event.previous_focus_count = 1  # 事件系统此前记录的数字

    focus_wrapper = SimpleNamespace(text="2人专注中")
    with patch.object(observation, "expand_rescan_and_collapse", new_callable=AsyncMock) as mock_rescan:
        await event.handle("focus_count", [focus_wrapper])
        # 验证全量重扫未被触发！
        mock_rescan.assert_not_called()
