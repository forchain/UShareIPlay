"""
Ticket #346: Targeted seating (:seat 2 <n>) with viewport sync pipeline.

Tests:
1. Direct row navigation with scroll phase propagation (band="top" / "bottom") without sequential scanning.
2. Snapshot update and abort without clicking when target seat is occupied in post-scroll page_source.
3. Coordinate bounds click and confirm seating when empty, followed by snapshot and focus count updates.
4. Clean panel collapse on completion or error.
5. Suppression of downstream focus count rescan (+1 count).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lxml import etree

from tests.seat_fixtures import (
    SEAT_DOM_FIXTURES,
    FakeSeatUI,
    make_handler,
)
from ushareiplay.events.focus_count import FocusCountEvent
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def reset_state():
    # RoomState 必须走 reset_instance()：只把 _instance 置 None 解不掉
    # _singleton_initialized，instance() 会返回 None 而不是抛 SingletonError，
    # 于是 FocusCountEvent 的兜底 except 吞掉 AttributeError，事件到不了
    # on_focus_count —— 反 back-trigger 断言就成了空断言。
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    RoomState.reset_instance()
    RoomState.initialize()
    yield
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    RoomState.reset_instance()


def _load_xml(filename: str) -> str:
    return (SEAT_DOM_FIXTURES / filename).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_sit_at_specific_seat_navigates_directly_to_target_row_and_collapses():
    """目标麦位导航直达目标排，传播对应相位，且最终收起面板。"""
    handler = make_handler()
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

    assert result == {"success": "Successfully took a seat"}
    # 确认直接滚动到 row 2（第 3 排），没有顺序扫描 row 0, 1
    assert fake_seat_ui.scrolled_rows == [2]
    # 确认面板已收起
    assert fake_seat_ui.collapsed is True


@pytest.mark.asyncio
async def test_sit_at_specific_seat_row1_clamps_to_top_before_claiming_band():
    """第二排（row 1）目标：#346 唯一没有测试覆盖的行，也是相位声明唯一无滚动背书的行。

    展开后面板默认位置未经真机证实，因此 row 1 必须先被真实滚到内容顶部夹住，
    band="top" 才是由本次滚动得出的相位，而不是一句假设。
    """
    handler = make_handler()
    handler.driver = MagicMock()
    handler.driver.page_source = _load_xml("expanded_top_with_anchor.xml")  # 6 号位为空

    observation = SeatObservationManager.initialize(handler)
    observation._last_focus_count = 1

    fake_seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager(handler=handler, seat_ui=fake_seat_ui, observation=observation)

    confirm_elem = MagicMock()
    handler.element_finder.wait_for_element_clickable = MagicMock(
        side_effect=lambda key, **kwargs: confirm_elem if key == "confirm_seat" else None
    )

    result = await seating.sit_at_specific_seat(6)  # desk 2 右座 = 第二排

    assert result == {"success": "Successfully took a seat"}
    # 相位由真实滚动得到：row 1 也要滚到顶部夹住，不是靠「默认就在顶部」的假设
    assert fake_seat_ui.scrolled_rows == [0]

    # 夹具里 1 号位群主占座（顶相位读数落到 1 号位）；房主本来就在座，
    # sit_at_specific_seat 是一次移动：旧位必须腾出，专注人数不变。
    # （真机 09-28 18:07:08：10→11 换座被当成新增 +1，凭空把 RoomState
    # 推成 2，随即被真实读数 1 判背离、引爆全量重扫。）
    assert observation.seats[1].occupied is False
    handler.gesture_handler.click_at.assert_called_once()
    click_x, click_y = handler.gesture_handler.click_at.call_args.args
    # 6 号位 bounds=[170,810][305,977]（desk 2 右座）
    assert 170 <= click_x <= 305
    assert 810 <= click_y <= 977

    assert observation.seats[6].occupied is True
    assert observation.seats[6].is_owner is True
    assert observation._last_focus_count == 1
    assert observation._reconciled_focus_count == 1
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

    assert result == {"error": "Seat 1 is already occupied by 群主"}

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

    assert result == {"success": "Successfully took a seat"}
    # 确认调用了坐标点击 gesture_handler.click_at
    handler.gesture_handler.click_at.assert_called_once()
    click_x, click_y = handler.gesture_handler.click_at.call_args.args
    # 检查坐标处于 2 号位 bounds 范围内（desk 0 右座 bounds=[170,576][305,743]）
    assert 170 <= click_x <= 305
    assert 576 <= click_y <= 743

    # 确认弹窗被点击
    confirm_elem.click.assert_called_once()

    # 快照被标记为群主占用；1 号位（夹具里房主的旧位）被移动腾出
    assert observation.seats[2].occupied is True
    assert observation.seats[2].is_owner is True
    assert observation.seats[2].username == "群主"
    assert observation.seats[1].occupied is False

    # 房主原本就在座（夹具 1 号位群主）：换座净人数为 0，基准不许动
    assert observation._last_focus_count == 1
    assert observation._reconciled_focus_count == 1

    # 面板收起
    assert fake_seat_ui.collapsed is True


@pytest.mark.asyncio
async def test_sit_at_specific_seat_reports_error_when_seat_is_unjudgable():
    """读不出判据（third state）时按「无法核验」报错，不得谎报成「有人占座」。"""
    handler = make_handler()
    handler.driver = MagicMock()
    # 去掉 2 号位所在桌位的右座子树：既非占座证据，也非空座证据
    root = etree.fromstring(_load_xml("expanded_top_with_anchor.xml").encode("utf-8"))
    for seat in root.xpath("//*[@resource-id='cn.soulapp.android:id/rightUserView']")[:1]:
        seat.getparent().remove(seat)
    handler.driver.page_source = etree.tostring(root, encoding="unicode")

    observation = SeatObservationManager.initialize(handler)
    fake_seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager(handler=handler, seat_ui=fake_seat_ui, observation=observation)

    result = await seating.sit_at_specific_seat(2)

    assert result == {"error": "Seat 2 could not be verified in viewport"}
    handler.gesture_handler.click_at.assert_not_called()


@pytest.mark.asyncio
async def test_sit_at_specific_seat_reports_error_when_gesture_click_unavailable():
    """拿不到 click_at 时必须直接报错，不能静默跳过点击再去等确认弹窗。"""
    handler = make_handler()
    handler.driver = MagicMock()
    handler.driver.page_source = _load_xml("expanded_top_with_anchor.xml")
    handler.gesture_handler = SimpleNamespace()  # 没有 click_at

    observation = SeatObservationManager.initialize(handler)
    fake_seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager(handler=handler, seat_ui=fake_seat_ui, observation=observation)

    handler.element_finder.wait_for_element_clickable = MagicMock(return_value=None)

    result = await seating.sit_at_specific_seat(2)

    assert result == {"error": "Gesture handler cannot click; seat 2 was not selected"}
    handler.element_finder.wait_for_element_clickable.assert_not_called()
    # 快照不得被标记为已就座
    assert observation.seats[2].occupied is False
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
    """换座成功后，下游专注人数事件不再触发背离全量重扫。"""
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

    # 就座 2 号位：夹具里房主已坐 1 号位 → 这是一次移动，净人数不变
    await seating.sit_at_specific_seat(2)
    assert observation._last_focus_count == 1
    assert observation._reconciled_focus_count == 1

    # 模拟 FocusCountEvent 处理「1人专注中」：换座后房间真实读数仍是 1
    event = FocusCountEvent(handler)
    event.previous_focus_count = 0  # 事件系统此前记录的数字

    focus_wrapper = SimpleNamespace(text="1人专注中")
    with patch.object(observation, "expand_rescan_and_collapse", new_callable=AsyncMock) as mock_rescan, \
            patch.object(
                observation, "on_focus_count", wraps=observation.on_focus_count
            ) as spy_on_focus_count:
        await event.handle("focus_count", [focus_wrapper])

        # 先证明事件真的走到了对账逻辑：否则 mock_rescan 未被调用是空断言
        # （RoomState 未初始化时 handle 的兜底 except 会在到达前就吞掉异常）。
        assert spy_on_focus_count.call_count == 1
        assert spy_on_focus_count.call_args.args == (0, 1)

        # 验证全量重扫未被触发！
        mock_rescan.assert_not_called()
