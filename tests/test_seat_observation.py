import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)


class DummyNode:
    def __init__(self, text="", bounds=None):
        self.text = text
        self.bounds = bounds or {"x": 0, "y": 0, "width": 100, "height": 100}
        self.clicked = False

    def click(self):
        self.clicked = True


class DummyDesk:
    def __init__(
        self,
        left_label="",
        left_occupied=False,
        right_label="",
        right_occupied=False,
        bounds=None,
        desk_index=None,
    ):
        self.children = {
            "left_seat": DummyNode(),
            "right_seat": DummyNode(),
            "left_state": DummyNode() if left_occupied else None,
            "right_state": DummyNode() if right_occupied else None,
            "left_label": DummyNode(left_label) if left_label else None,
            "right_label": DummyNode(right_label) if right_label else None,
        }
        self.bounds = bounds or {"x": 0, "y": 0, "width": 200, "height": 100}
        if desk_index is not None:
            self.desk_index = desk_index

    def find_child_element(self, key):
        return self.children.get(key)


@pytest.fixture(autouse=True)
def reset_observation():
    SeatObservationManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()


def test_format_3row_layout_visual_representation():
    manager = SeatObservationManager.initialize(None)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="群主", is_owner=True)
    manager.seats[2] = SeatSlot(seat_number=2, occupied=False)
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="张三")
    manager.seats[7] = SeatSlot(seat_number=7, occupied=True, username="李四")
    manager.seats[11] = SeatSlot(seat_number=11, occupied=True, username="王五")

    layout = manager.format_3row_layout("测试触发")
    lines = layout.splitlines()

    assert "[FocusSeatObservation] 专注麦位状态变更 (触发源: 测试触发):" in lines[0]
    assert "第一排: [1号: 群主] [2号: 空闲]  |  [3号: 张三] [4号: 空闲]" in lines[1]
    assert "第二排: [5号: 空闲] [6号: 空闲]  |  [7号: 李四] [8号: 空闲]" in lines[2]
    assert "第三排: [9号: 空闲] [10号: 空闲]  |  [11号: 王五] [12号: 空闲]" in lines[3]


def test_map_desks_to_indices_by_number_labels():
    manager = SeatObservationManager.initialize(None)
    desk_row0_left = DummyDesk(left_label="1", right_label="2")
    desk_row1_right = DummyDesk(left_label="7", right_label="8")
    desk_row2_left = DummyDesk(left_label="9", right_label="10")

    desks = [desk_row1_right, desk_row0_left, desk_row2_left]
    mapped = manager.map_desks_to_indices(desks)

    indices = [idx for idx, d in mapped]
    assert indices == [0, 3, 4]


def test_map_desks_to_indices_fallback_by_coordinates():
    manager = SeatObservationManager.initialize(None)
    # 假设所有 label 都是占座者昵称，无数字，靠坐标聚类
    desk0 = DummyDesk(left_label="群主", right_label="A", bounds={"x": 50, "y": 100, "width": 100, "height": 50})
    desk1 = DummyDesk(left_label="B", right_label="C", bounds={"x": 200, "y": 100, "width": 100, "height": 50})
    desk2 = DummyDesk(left_label="D", right_label="E", bounds={"x": 50, "y": 200, "width": 100, "height": 50})
    desk3 = DummyDesk(left_label="F", right_label="G", bounds={"x": 200, "y": 200, "width": 100, "height": 50})

    desks = [desk3, desk0, desk2, desk1]
    mapped = manager.map_desks_to_indices(desks)

    indices = [idx for idx, d in mapped]
    assert indices == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_observe_visible_desks_detects_changes_and_diff():
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    mock_handler.controller = MagicMock()
    mock_handler.controller.acquire_ui_lock = AsyncMock()
    mock_handler.controller.release_ui_lock = MagicMock()
    mock_handler.element_finder = MagicMock()

    manager = SeatObservationManager.initialize(mock_handler)

    desk0 = DummyDesk(left_label="群主", left_occupied=True, right_label="2", right_occupied=False, desk_index=0)
    desk1 = DummyDesk(left_label="3", left_occupied=False, right_label="4", right_occupied=False, desk_index=1)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd_mgr:
        notify_mock = AsyncMock()
        mock_cmd_mgr.return_value.notify_focus_count_change = notify_mock

        # First observation: 群主 seated at seat 1
        changed = await manager.observe_visible_desks([desk0, desk1])
        assert changed is True
        assert manager.seats[1].occupied is True
        assert manager.seats[1].is_owner is True
        assert manager.seats[2].occupied is False

        # Verify notify was called with 群主 sit_down
        notify_mock.assert_awaited_once()
        args, kwargs = notify_mock.call_args
        assert kwargs["changed_users"] == ["群主"]
        assert kwargs["seat_info"]["群主"]["seat_number"] == 1
        assert kwargs["seat_info"]["群主"]["action"] == "sit_down"


@pytest.mark.asyncio
async def test_observe_visible_desks_inspects_new_occupant():
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    mock_handler.controller = MagicMock()
    mock_handler.controller.acquire_ui_lock = AsyncMock()
    mock_handler.controller.release_ui_lock = MagicMock()
    mock_handler.key_actions = MagicMock()
    mock_handler.element_finder = MagicMock()
    # Mock popup returns "Bob"
    mock_handler.element_finder.wait_for_any_element.return_value = ("souler_name", DummyNode("Bob"))

    manager = SeatObservationManager.initialize(mock_handler)

    # Desk 0: seat 1 is occupied without username text (label is "管理")
    desk0 = DummyDesk(left_label="管理", left_occupied=True, right_label="2", right_occupied=False, desk_index=0)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd_mgr:
        mock_cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        changed = await manager.observe_visible_desks([desk0])
        assert changed is True
        assert manager.seats[1].occupied is True
        assert manager.seats[1].username == "Bob"
        # Confirm popup inspection clicked and pressed back
        assert mock_handler.key_actions.press_back.called


@pytest.mark.asyncio
async def test_focus_divergence_triggers_active_expansion():
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    mock_handler.controller = MagicMock()
    mock_handler.controller.acquire_ui_lock = AsyncMock()
    mock_handler.controller.release_ui_lock = MagicMock()
    mock_handler.key_actions = MagicMock()
    mock_handler.element_finder = MagicMock()

    mock_seat_ui = MagicMock()
    mock_seat_ui.expand_seats = AsyncMock(return_value=True)
    mock_seat_ui.collapse_seats = AsyncMock(return_value=True)

    manager = SeatObservationManager.initialize(mock_handler)
    manager._seat_ui = mock_seat_ui

    # Visible desks currently have 1 person (seat 1)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="Alice")

    # Expanded desks mock: shows Alice on seat 1, and David on seat 7 (row 1 right desk)
    desk0 = DummyDesk(left_label="Alice", left_occupied=True, right_label="2", desk_index=0)
    desk3 = DummyDesk(left_label="David", left_occupied=True, right_label="8", desk_index=3)
    mock_handler.element_finder.find_elements.return_value = [desk0, desk3]

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd_mgr:
        notify_mock = AsyncMock()
        mock_cmd_mgr.return_value.notify_focus_count_change = notify_mock

        # When focus_count changes to 2 (diverges from known seated count = 1)
        diverged = await manager.on_focus_count(before=1, current_focus_count=2)

        assert diverged is True
        # Verify expand and collapse were both called!
        mock_seat_ui.expand_seats.assert_awaited_once()
        mock_seat_ui.collapse_seats.assert_awaited_once()
        # Verify seat 7 is now recognized as occupied by David
        assert manager.seats[7].occupied is True
        assert manager.seats[7].username == "David"
        # Verify David's sit_down triggered notification
        assert "David" in notify_mock.call_args[1]["changed_users"]
