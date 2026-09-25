from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lxml import etree

from tests.seat_fixtures import build_desk_wrapper, make_handler, soul_elements
from ushareiplay.core.element_wrapper import ElementWrapper
from ushareiplay.events.focus_count import FocusCountEvent, __elements__, __multiple__
from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def reset_singletons():
    SeatObservationManager.reset_instance()
    RoomState.reset_instance()
    RoomState.initialize()
    yield
    SeatObservationManager.reset_instance()
    RoomState.reset_instance()


def test_focus_count_event_metadata():
    assert "focus_count" in __elements__
    assert "seat_desk" in __elements__
    assert __multiple__ is True


def test_seat_desk_is_registered_before_focus_count():
    """R1：EventManager 按 __elements__ 顺序分发，seat_desk 必须排在前面。

    先观测本页可见麦位、再判人数背离，否则每次可视上座都拿旧快照去比，
    被误判成背离而白展开一次面板。
    """
    assert __elements__ == ["seat_desk", "focus_count"]


def _focus_count_wrapper(text: str) -> ElementWrapper:
    resource_id = soul_elements()["focus_count"]
    root = etree.fromstring(
        f'<hierarchy><node resource-id="{resource_id}" text="{text}"/></hierarchy>'.encode()
    )
    return ElementWrapper(root.xpath("//node")[0], None, "focus_count")


@pytest.mark.asyncio
async def test_same_round_visible_sitdown_does_not_trigger_expansion():
    """R1 回归：同一页里 focus_count 与 seat_desk 同时变化时不得主动展开。

    按 EventManager 的分发顺序（__elements__）走一轮：先看到有人落座，人数
    随后从 0 变 1 —— 此时在座数已经同步，不构成背离。
    """
    handler = make_handler()
    observation = SeatObservationManager.initialize(handler)
    event = FocusCountEvent(handler=handler)
    observation.expand_rescan_and_collapse = AsyncMock(return_value=False)

    desk = build_desk_wrapper(handler, left="张三", right="2", left_occupied=True, y=100)
    focus_wrapper = _focus_count_wrapper("1人专注中")

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        for key in __elements__:
            if key == "seat_desk":
                await event.handle("seat_desk", [desk])
            else:
                await event.handle("focus_count", focus_wrapper)

    observation.expand_rescan_and_collapse.assert_not_awaited()
    assert notify.await_args.kwargs["changed_users"] == ["张三"]


@pytest.mark.asyncio
async def test_focus_count_event_handles_focus_count():
    handler = MagicMock()
    handler.logger = MagicMock()
    observation = SeatObservationManager.initialize(handler)
    observation.on_focus_count = AsyncMock()

    event = FocusCountEvent(handler=handler)

    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人专注中"

    # First update: from None to 5
    res = await event.handle("focus_count", mock_wrapper)
    assert res is False
    assert RoomState.instance().focus_count == 5
    observation.on_focus_count.assert_awaited_once_with(None, 5)

    # Second update with same count should be ignored
    observation.on_focus_count.reset_mock()
    res2 = await event.handle("focus_count", mock_wrapper)
    assert res2 is False
    observation.on_focus_count.assert_not_called()

    # Third update with changed count: 6
    mock_wrapper.text = "6"
    res3 = await event.handle("focus_count", mock_wrapper)
    assert res3 is False
    assert RoomState.instance().focus_count == 6
    observation.on_focus_count.assert_awaited_once_with(5, 6)


@pytest.mark.asyncio
async def test_focus_count_event_handles_seat_desk():
    handler = MagicMock()
    handler.logger = MagicMock()
    observation = SeatObservationManager.initialize(handler)
    observation.observe_visible_desks = AsyncMock()

    event = FocusCountEvent(handler=handler)
    event.previous_focus_count = 3

    desk1 = MagicMock()
    desk2 = MagicMock()

    res = await event.handle("seat_desk", [desk1, desk2])
    assert res is False
    observation.observe_visible_desks.assert_awaited_once_with([desk1, desk2], current_focus_count=3)
