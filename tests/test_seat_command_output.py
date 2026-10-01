import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from ushareiplay.commands.seat import SeatCommand
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager, SeatSlot
from ushareiplay.models.message_info import MessageInfo


@pytest.fixture(autouse=True)
def reset_seat_observation():
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()


def make_dummy_controller():
    logger = MagicMock()
    soul_handler = SimpleNamespace(
        logger=logger,
        log_error=MagicMock(),
    )
    return SimpleNamespace(
        soul_handler=soul_handler,
        music_handler=None,
        logger=logger,
    ), logger


@pytest.mark.asyncio
async def test_seat_command_success_logs_layout():
    controller, logger = make_dummy_controller()
    obs = SeatObservationManager.initialize(controller.soul_handler)
    obs.seats[1] = SeatSlot(seat_number=1, occupied=True, username="Alice")

    cmd = SeatCommand(controller)
    msg = MessageInfo(content=":seat 2 1", nickname="Alice")

    SeatManager.reset_instance()
    mock_seat_mgr = SeatManager.initialize()
    mock_seat_mgr.take_seat = AsyncMock(return_value={"success": "Took seat 1"})

    res = await cmd.process(msg, ["2", "1"])
    assert res == {"success": "Took seat 1"}

    # Verify logger.info was called with format_3row_layout output
    info_calls = [call[0][0] for call in logger.info.call_args_list if call[0]]
    layout_logs = [log for log in info_calls if "[FocusSeatObservation] 专注麦位状态变更" in str(log)]
    assert len(layout_logs) == 1
    assert "触发源: seat命令执行" in layout_logs[0]
    assert "[1号: Alice]" in layout_logs[0]


@pytest.mark.asyncio
async def test_seat_command_failure_logs_layout():
    controller, logger = make_dummy_controller()
    obs = SeatObservationManager.initialize(controller.soul_handler)
    obs.seats[2] = SeatSlot(seat_number=2, occupied=True, username="Bob")

    cmd = SeatCommand(controller)
    msg = MessageInfo(content=":seat 2 2", nickname="Alice")

    SeatManager.reset_instance()
    mock_seat_mgr = SeatManager.initialize()
    mock_seat_mgr.take_seat = AsyncMock(return_value={"error": "Seat 2 is already occupied"})

    res = await cmd.process(msg, ["2", "2"])
    assert res == {"error": "Seat 2 is already occupied"}

    info_calls = [call[0][0] for call in logger.info.call_args_list if call[0]]
    layout_logs = [log for log in info_calls if "[FocusSeatObservation] 专注麦位状态变更" in str(log)]
    assert len(layout_logs) == 1
    assert "触发源: seat命令执行" in layout_logs[0]
    assert "[2号: Bob]" in layout_logs[0]


@pytest.mark.asyncio
async def test_seat_command_invalid_param_logs_layout():
    controller, logger = make_dummy_controller()
    obs = SeatObservationManager.initialize(controller.soul_handler)

    cmd = SeatCommand(controller)
    msg = MessageInfo(content=":seat invalid", nickname="Alice")

    res = await cmd.process(msg, ["invalid"])
    assert "error" in res

    info_calls = [call[0][0] for call in logger.info.call_args_list if call[0]]
    layout_logs = [log for log in info_calls if "[FocusSeatObservation] 专注麦位状态变更" in str(log)]
    assert len(layout_logs) == 1
    assert "触发源: seat命令执行" in layout_logs[0]


@pytest.mark.asyncio
async def test_seat_command_exception_logs_layout():
    controller, logger = make_dummy_controller()
    obs = SeatObservationManager.initialize(controller.soul_handler)

    cmd = SeatCommand(controller)
    msg = MessageInfo(content=":seat 2 1", nickname="Alice")

    SeatManager.reset_instance()
    mock_seat_mgr = SeatManager.initialize()
    mock_seat_mgr.take_seat = AsyncMock(side_effect=RuntimeError("UI crash"))

    res = await cmd.process(msg, ["2", "1"])
    assert "error" in res

    info_calls = [call[0][0] for call in logger.info.call_args_list if call[0]]
    layout_logs = [log for log in info_calls if "[FocusSeatObservation] 专注麦位状态变更" in str(log)]
    assert len(layout_logs) == 1
    assert "触发源: seat命令执行" in layout_logs[0]
