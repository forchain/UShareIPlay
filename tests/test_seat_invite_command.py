"""`:seat 5 <座位号> [用户]` 的测试：参数解析、可见昵称解析、转交座位层。

座位层（`SeatSubsystem.invite_user_to_seat`）与弹窗驱动各有自己的测试文件；这里
只钉住命令这一层的契约：**座位号必须是 1~12、目标用户缺省为发起人、拿到的名字
必须先解析成房间里当前可见的那个名字**（分身名）。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ushareiplay.commands.seat import SeatCommand
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
from ushareiplay.models.message_info import MessageInfo


@pytest.fixture(autouse=True)
def reset_singletons():
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()


def make_controller():
    logger = MagicMock()
    soul_handler = SimpleNamespace(logger=logger, log_error=MagicMock())
    return SimpleNamespace(soul_handler=soul_handler, music_handler=None, logger=logger)


def make_command(resolved_name=None):
    controller = make_controller()
    command = SeatCommand(controller)
    info_manager = MagicMock()
    info_manager.resolve_visible_username = AsyncMock(
        return_value=resolved_name if resolved_name is not None else "可见昵称"
    )
    command._info_manager = info_manager
    return command, info_manager


def make_seat_manager(result=None):
    manager = SeatManager.initialize()
    manager.invite_user_to_seat = AsyncMock(
        return_value=result if result is not None else {"success": "已邀请 可见昵称 入座 3 号座位"}
    )
    return manager


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


async def test_seat_5_defaults_the_target_to_the_sender():
    """用户留空：邀请对象就是命令发起人。"""
    command, info_manager = make_command(resolved_name="发起人分身")
    manager = make_seat_manager()
    msg = MessageInfo(content=":seat 5 3", nickname="发起人")

    result = await command.process(msg, ["5", "3"])

    assert result == {"success": "已邀请 可见昵称 入座 3 号座位"}
    info_manager.resolve_visible_username.assert_awaited_once_with("发起人")
    manager.invite_user_to_seat.assert_awaited_once_with(3, "发起人分身")


async def test_seat_5_invites_the_named_user():
    command, info_manager = make_command(resolved_name="对方分身")
    manager = make_seat_manager()
    msg = MessageInfo(content=":seat 5 3 Bob", nickname="发起人")

    await command.process(msg, ["5", "3", "Bob"])

    info_manager.resolve_visible_username.assert_awaited_once_with("Bob")
    manager.invite_user_to_seat.assert_awaited_once_with(3, "对方分身")


async def test_seat_5_rejects_a_seat_number_out_of_range():
    command, _ = make_command()
    manager = make_seat_manager()
    msg = MessageInfo(content=":seat 5 99", nickname="发起人")

    result = await command.process(msg, ["5", "99"])

    assert result == {"error": "Invalid seat number. Must be between 1 and 12"}
    manager.invite_user_to_seat.assert_not_called()


async def test_seat_5_requires_a_seat_number():
    """:seat 5 少了座位号：如实报错，不猜。"""
    command, _ = make_command()
    manager = make_seat_manager()
    msg = MessageInfo(content=":seat 5", nickname="发起人")

    result = await command.process(msg, ["5"])

    assert "error" in result
    manager.invite_user_to_seat.assert_not_called()


async def test_seat_5_rejects_a_non_numeric_seat_number():
    command, _ = make_command()
    manager = make_seat_manager()
    msg = MessageInfo(content=":seat 5 abc", nickname="发起人")

    result = await command.process(msg, ["5", "abc"])

    assert result == {"error": "Invalid seat number. Must be between 1 and 12"}
    manager.invite_user_to_seat.assert_not_called()


# ---------------------------------------------------------------------------
# 用法提示
# ---------------------------------------------------------------------------


async def test_invalid_command_message_lists_the_invite_form():
    command, _ = make_command()
    msg = MessageInfo(content=":seat 9", nickname="发起人")

    result = await command.process(msg, ["9"])

    assert "5 <seat_number> [username]" in result["error"]
