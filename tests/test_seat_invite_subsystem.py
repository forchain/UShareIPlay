"""SeatSubsystem.invite_user_to_seat 的测试：滚入视口、核验空座、点开弹窗、邀请、关窗。

弹窗那一段用真实实现（`SeatInviteDriver`）跑，只有「邀请入座」弹窗的元素查找
是替身（tests/test_seat_invite_driver.py 里那套）。座位面板与视口读数都是替身：
本测试关心的是**流程与顺序**（先核验空座再点、任何分支都要关弹窗并收起面板），
不是 Appium 的真实几何。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.seat_fixtures import (
    FAKE_SEAT_BOUNDS,
    FakeSeatDesk,
    FakeSeatObservation,
    FakeSeatUI,
)
from tests.test_seat_invite_driver import InviteRow, make_invite_handler

from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

SEAT_BOUNDS = FAKE_SEAT_BOUNDS


def make_subsystem(
    pages=None,
    close_button=None,
    occupied=False,
    unjudgable=False,
    invite_driver=None,
):
    handler = make_invite_handler(pages=pages, close_button=close_button)
    desks = [FakeSeatDesk() for _ in range(6)]
    seat_ui = FakeSeatUI(desks=desks)

    if occupied:
        info = {"occupied": True, "is_empty": False, "label": "群主"}
    elif unjudgable:
        info = {"occupied": False, "is_empty": False}
    else:
        info = {"occupied": False, "is_empty": True}

    observation = FakeSeatObservation(observed={3: (desks[1], "left", info)})
    subsystem = SeatSubsystem(
        handler=handler, seat_ui=seat_ui, observation=observation,
        invite_driver=invite_driver,
    )
    return subsystem, handler, seat_ui, observation


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seat_number", [0, 13, -1])
async def test_invite_user_to_seat_rejects_a_seat_number_out_of_range(seat_number):
    subsystem, handler, seat_ui, _ = make_subsystem()

    result = await subsystem.invite_user_to_seat(seat_number, "Alice")

    assert "error" in result
    handler.gesture_handler.click_at.assert_not_called()


async def test_invite_user_to_seat_requires_a_target_name():
    subsystem, handler, seat_ui, _ = make_subsystem()

    result = await subsystem.invite_user_to_seat(3, "")

    assert "error" in result
    handler.gesture_handler.click_at.assert_not_called()


# ---------------------------------------------------------------------------
# 座位被占用
# ---------------------------------------------------------------------------


async def test_invite_user_to_seat_refuses_an_occupied_seat_without_opening_the_sheet():
    """座位有人：直接拦下，连空座都不点 —— 弹窗根本没机会开。"""
    subsystem, handler, seat_ui, _ = make_subsystem(
        pages=[[InviteRow("Alice", "邀请")]], occupied=True
    )

    result = await subsystem.invite_user_to_seat(3, "Alice")

    assert result == {"error": "座位 3 已被占用"}
    handler.gesture_handler.click_at.assert_not_called()
    # 面板照样要收起
    assert seat_ui.collapsed is True


async def test_invite_user_to_seat_refuses_a_seat_it_cannot_judge():
    """读不到任何判据（第三种状态）：按「不是空座」处理，不点。"""
    subsystem, handler, seat_ui, _ = make_subsystem(
        pages=[[InviteRow("Alice", "邀请")]], unjudgable=True
    )

    result = await subsystem.invite_user_to_seat(3, "Alice")

    assert "error" in result
    handler.gesture_handler.click_at.assert_not_called()
    assert seat_ui.collapsed is True


# ---------------------------------------------------------------------------
# 目标不在列表里 / 目标已在座
# ---------------------------------------------------------------------------


async def test_invite_user_to_seat_closes_the_sheet_when_the_target_is_not_in_the_list():
    """目标已离房：列表里翻不到，如实报错并把弹窗关掉。"""
    close_button = MagicMock()
    subsystem, handler, seat_ui, _ = make_subsystem(
        pages=[[InviteRow("Bob", "邀请")]], close_button=close_button
    )

    result = await subsystem.invite_user_to_seat(3, "Alice")

    assert result == {"error": "未在邀请列表中找到 Alice"}
    assert close_button.click.called is True
    assert seat_ui.collapsed is True
    handler.key_actions.press_back.assert_not_called()


async def test_invite_user_to_seat_refuses_to_invite_someone_who_is_already_seated():
    """目标写着「已上座」：不要再点一次邀请，关掉弹窗如实说明。"""
    close_button = MagicMock()
    subsystem, handler, seat_ui, _ = make_subsystem(
        pages=[[InviteRow("Alice", "已上座")]], close_button=close_button
    )

    result = await subsystem.invite_user_to_seat(3, "Alice")

    assert result == {"error": "Alice 已在座"}
    assert close_button.click.called is True
    assert seat_ui.collapsed is True
    handler.key_actions.press_back.assert_not_called()


# ---------------------------------------------------------------------------
# 顺利邀请
# ---------------------------------------------------------------------------


async def test_invite_user_to_seat_clicks_invite_and_closes_the_sheet():
    """顺利路径：滚入视口 → 点空座 → 弹窗里找到人 → 点「邀请」→ 关弹窗 → 收面板。"""
    close_button = MagicMock()
    invite_row = InviteRow("Alice", "邀请")
    subsystem, handler, seat_ui, observation = make_subsystem(
        pages=[[invite_row]], close_button=close_button
    )

    result = await subsystem.invite_user_to_seat(3, "Alice")

    assert result == {"success": "已邀请 Alice 入座 3 号座位"}
    # 空座被点开了（落在座位 bounds 中心）
    handler.gesture_handler.click_at.assert_called_once()
    click_x, click_y = handler.gesture_handler.click_at.call_args.args
    assert click_x == SEAT_BOUNDS["x"] + SEAT_BOUNDS["width"] // 2
    assert click_y == SEAT_BOUNDS["y"] + SEAT_BOUNDS["height"] // 2
    # 弹窗里的「邀请」被点了一次
    assert invite_row.operation_node.clicked is True
    # 弹窗被关掉、面板被收起
    assert close_button.click.called is True
    assert seat_ui.collapsed is True
    handler.key_actions.press_back.assert_not_called()


async def test_invite_user_to_seat_scrolls_the_target_row_into_the_viewport():
    """目标座位所在的那一排要滚进视口，相位由这次滚动决定。"""
    subsystem, handler, seat_ui, observation = make_subsystem(
        pages=[[InviteRow("Alice", "邀请")]]
    )

    await subsystem.invite_user_to_seat(3, "Alice")

    assert seat_ui.scrolled_rows == [0]
    assert observation.bands == ["top"]


# ---------------------------------------------------------------------------
# 异常退出：弹窗要关、面板要收
# ---------------------------------------------------------------------------


class ExplodingInviteDriver:
    """在弹窗里找人的时候炸掉的邀请驱动（模拟 Appium 读列表时的意外）。"""

    def __init__(self, handler=None):
        self.handler = handler
        self.closed = False

    async def wait_until_open(self, timeout: float = 3.0) -> bool:
        return True

    async def find_row(self, visible_name, max_pages: int = 10):
        raise RuntimeError("读邀请列表时炸了")

    def click_invite(self, row) -> bool:
        return True

    def close(self) -> bool:
        self.closed = True
        return True


async def test_an_exception_in_the_invite_flow_still_closes_the_sheet_and_the_panel():
    """异常退出也要收尾：弹窗关掉、面板收起、错误如实返回（#453 验收要求）。"""
    driver = ExplodingInviteDriver()
    subsystem, handler, seat_ui, observation = make_subsystem(invite_driver=driver)

    result = await subsystem.invite_user_to_seat(3, "Alice")

    assert "error" in result, "异常必须变成一个错误结果，不能把异常甩给调用方"
    assert driver.closed is True, "异常退出时弹窗的 X 必须被点掉"
    assert seat_ui.collapsed is True, "异常退出时座位面板必须收起"
    handler.key_actions.press_back.assert_not_called()
