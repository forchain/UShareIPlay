"""复现生产事故：目标坐在别人旁边时，:seat 报「该房间里没有这个人」。

真机现象（10-08 12:53:18~12:53:25）：

    scroll_to_row: Scrolled seat panel to row 1 for desk 1
    accompany_user: Found user 'Chainer' at desk 1, left side
    scroll_to_row: Scrolled seat panel to row 3 for desk 5
    collapse: Collapsed seat panel
    Failed to apply for seat, because User 不约儿童🐏🐏 not found on any seat

而同一次运行的座次表里，这个人明明在麦上（5 号桌右位 = 10 号位），
且左边（9 号位群主）同样有人：

    第三排: [9号: 群主(Joyer)] [10号: 管理(不约儿童🐏🐏)] | [11号: 已占用] [12号: 管理]

`accompany_user` 原来只点名「这张桌位恰好只坐了一个人」的桌位，两侧都占座的
桌位被整张 `continue` 跳过 —— 目标所在的桌位根本没被点名，
最后报出与事实相反的「not found on any seat」。

修复后的契约：
1. 两侧都占座的桌位也要逐侧点名；
2. 目标确实在那儿时回报「旁边没有空位」，而不是谎称找不到；
3. 两侧都不是目标时继续看后面的桌位（不能就此收工）。
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.seat_fixtures import FakeSeatUI, RawSeatDesk, soul_elements
from tests.test_seat_panel_delegation import (
    AVATAR,
    CANONICAL,
    IDENTITY,
    RecordingNode,
    make_popup_handler,
)
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.seat_manager.seat_panel_driver import AvatarTapPolicy, SeatCardView
from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem


@pytest.fixture(autouse=True)
def _no_sleeps(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


@pytest.fixture
def same_identity(monkeypatch):
    async def _is_same_identity(left, right):
        return IDENTITY.get(left, left) == IDENTITY.get(right, right)

    monkeypatch.setattr(UserDAO, "is_same_identity", _is_same_identity)


def _desk(events, left_occupied, right_occupied, right_label="2"):
    """一张桌位的 raw WebElement 替身（展开重扫路径的形状）。"""
    elements = soul_elements()
    children = {}
    for side, occupied in (("left", left_occupied), ("right", right_occupied)):
        label = right_label if side == "right" else ""
        children[elements[f"{side}_seat"]] = RecordingNode(
            events,
            f"sit_{side}",
            text="",
            children={elements[f"{side}_label"]: SimpleNamespace(text=label)},
        )
        if occupied:
            children[elements[f"{side}_state"]] = RecordingNode(events, f"tap_{side}")
        else:
            children[elements[f"{side}_default_name"]] = SimpleNamespace(text="点击入座")
    return RawSeatDesk(children, location={"x": 40, "y": 600})


class ScriptedDriver:
    """按 (桌位序号, 侧) 返回对应人名的点名替身。

    真实链路读的是该侧那张名片上的昵称，所以每侧必须给各自的答案；
    固定返回同一个人会让「跳过整张桌位」这类 bug 测不出来。
    """

    def __init__(self, script):
        # script: {(desk_index, side): name or None}
        self.script = script
        self.calls = []
        self._desk_index = 0

    @asynccontextmanager
    async def avatar_card(
        self, desk, side, seat_number, *, tap_target=AvatarTapPolicy.STATE_THEN_SEAT
    ):
        self.calls.append((self._desk_index, side, seat_number, tap_target))
        name = self.script.get((self._desk_index, side))
        yield SeatCardView(opened=True, name=name)

    def advance(self):
        self._desk_index += 1

    def tap_targets(self):
        return [call[3] for call in self.calls]


@pytest.mark.asyncio
async def test_target_sitting_beside_another_is_not_reported_as_missing(same_identity):
    """目标与别人同坐一桌：必须被点名，报「旁边没有空位」而不是「找不到」。"""
    events = []
    desk = _desk(events, left_occupied=True, right_occupied=True)
    handler, _finder = make_popup_handler(events, popup_name=AVATAR)
    driver = ScriptedDriver({(0, "left"): "群主", (0, "right"): AVATAR})

    subsystem = SeatSubsystem(handler, seat_ui=FakeSeatUI([desk]), panel_driver=driver)

    result = await subsystem.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"error": f"User {CANONICAL} has no empty adjacent seat"}, result
    assert driver.calls, "两侧都占座的桌位也必须点名，否则目标永远读不到"


@pytest.mark.asyncio
async def test_neighbour_is_identified_before_reporting_no_adjacent_seat(same_identity):
    """先点名再判空位：不能因为「反正没空位」就跳过读身份。"""
    events = []
    desk = _desk(events, left_occupied=True, right_occupied=True)
    handler, _finder = make_popup_handler(events, popup_name=AVATAR)
    driver = ScriptedDriver({(0, "left"): "群主", (0, "right"): AVATAR})

    subsystem = SeatSubsystem(handler, seat_ui=FakeSeatUI([desk]), panel_driver=driver)

    await subsystem.accompany_user(CANONICAL, sender_username=CANONICAL)

    probed = [(idx, side) for idx, side, _n, _p in driver.calls]
    assert (0, "right") in probed, "目标所在的右侧必须被点名"
    assert (0, "left") in probed, "两侧都占座的桌位两侧都要点名"


@pytest.mark.asyncio
async def test_fully_occupied_desk_without_the_target_keeps_scanning(same_identity):
    """两侧都占座但都不是目标：不能就此收工，后面还有别的桌位。"""
    events = []
    neighbour_desk = _desk(events, left_occupied=True, right_occupied=True)
    target_desk = _desk(events, left_occupied=False, right_occupied=True)
    handler, _finder = make_popup_handler(events, popup_name=AVATAR)

    driver = ScriptedDriver({(0, "left"): "路人甲", (0, "right"): "路人乙"})

    class _AdvancingDriver(ScriptedDriver):
        """座位子系统按顺序遍历桌位，替身跟着同样的游标走。"""

        def __init__(self, script):
            super().__init__(script)
            self.seen_desks = 0

        @asynccontextmanager
        async def avatar_card(self, desk, side, seat_number, *, tap_target=AvatarTapPolicy.STATE_THEN_SEAT):
            idx = 0 if desk is neighbour_desk else 1
            self.calls.append((idx, side, seat_number, tap_target))
            name = self.script.get((idx, side))
            yield SeatCardView(opened=True, name=name)

    scripted = _AdvancingDriver({(0, "left"): "路人甲", (0, "right"): "路人乙"})
    subsystem = SeatSubsystem(
        handler, seat_ui=FakeSeatUI([neighbour_desk, target_desk]), panel_driver=scripted
    )

    result = await subsystem.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"error": f"User {CANONICAL} not found on any seat"}, result
    assert (0, "left") in [(i, s) for i, s, _n, _p in scripted.calls], (
        "两侧都占座的桌位也要点名，否则整桌被跳过"
    )


@pytest.mark.asyncio
async def test_target_on_a_later_desk_is_still_found_after_a_full_desk(same_identity):
    """前面一张满座桌位不是目标时，不能因此放弃后面真正有目标的桌位。"""
    events = []
    full_desk = _desk(events, left_occupied=True, right_occupied=True)
    target_desk = _desk(events, left_occupied=False, right_occupied=True)
    handler, _finder = make_popup_handler(events, popup_name=AVATAR)

    class _ByIdentityDriver(ScriptedDriver):
        @asynccontextmanager
        async def avatar_card(self, desk, side, seat_number, *, tap_target=AvatarTapPolicy.STATE_THEN_SEAT):
            idx = 0 if desk is full_desk else 1
            self.calls.append((idx, side, seat_number, tap_target))
            name = "路人" if idx == 0 else AVATAR
            yield SeatCardView(opened=True, name=name)

    driver = _ByIdentityDriver({})
    subsystem = SeatSubsystem(
        handler, seat_ui=FakeSeatUI([full_desk, target_desk]), panel_driver=driver
    )

    result = await subsystem.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"success": "Successfully took a seat"}, result