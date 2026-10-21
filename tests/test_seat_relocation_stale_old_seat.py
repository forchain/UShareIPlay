"""`/seat` 换座后，旧位子不能被落座后那次视口重读写回机器人。

真机 10-10 19:33:41–44 的症状：机器人（Joyer，群主）从 11 号位换到 9 号位（陪 10 号管理）。
`_take_seat` 先按占座游标把 11 号位腾空，然后落座后的视口重读撞上还没重绘的面板 ——
11 号仍渲染「群主」、9 号仍渲染空座 —— 于是 11 号被重新写成「群主(Joyer)」并打进
「视口同步」座次表。紧接着 `mark_owner_seated(9)` 的 stale 清理又静默把 11 号清掉，
最终快照是对的，但日志轨迹里机器人在 11 号位出现过、换座这件事却没有任何一行记录。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.seat_fixtures import (
    FakeElementFinder,
    FakeSeatUI,
    build_live_desk_wrappers_for,
    build_live_page_source,
    build_live_raw_desks_for,
    soul_elements,
)
from ushareiplay.commands.seat import SeatCommand
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)
from ushareiplay.models.message_info import MessageInfo

OWNER = "Joyer"


@pytest.fixture(autouse=True)
def reset_seat_singletons():
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()


class _ConfirmableFinder(FakeElementFinder):
    """补上 `_confirm_seat` 需要的确认件，与 ElementFinder 同名契约。"""

    def wait_for_element_clickable(self, element_key, timeout=10):
        node = SimpleNamespace(text="", clicked=False)
        node.click = lambda: setattr(node, "clicked", True)
        return node


def _info_lines(logger):
    return [str(call[0][0]) for call in logger.info.call_args_list if call[0]]


def _layout_logs(logger, trigger_source):
    return [
        line
        for line in _info_lines(logger)
        if "[FocusSeatObservation] 专注麦位状态变更" in line
        and f"触发源: {trigger_source}" in line
    ]


def _setup_relocation():
    """19:33 现场：机器人在 11 号位（陪 12 号管理），9 空、10 是管理；落座后面板还没重绘。"""
    scan = build_live_raw_desks_for({10: "管理", 11: "群主", 12: "管理"}, phase="full")
    stale_page = build_live_page_source({10: "管理", 11: "群主", 12: "管理"}, phase="bottom")

    handler = MagicMock()
    handler.logger = MagicMock()
    handler.config = {"elements": soul_elements(), "room_owner": OWNER}
    handler.controller = None
    handler.element_finder = _ConfirmableFinder(soul_elements(), desks=scan)
    handler.gesture_handler = MagicMock()
    handler.driver = MagicMock()
    handler.driver.page_source = stale_page

    obs = SeatObservationManager.initialize(handler)
    obs.seats[10] = SeatSlot(seat_number=10, occupied=True, username="不约儿童🐏🐏", label="管理")
    obs.seats[11] = SeatSlot(seat_number=11, occupied=True, username=OWNER, label="群主", is_owner=True)
    obs.seats[12] = SeatSlot(seat_number=12, occupied=True, username="儿童不易~🐏🐏", label="管理")
    obs._last_focus_count = 4
    obs._reconciled_focus_count = 4

    SeatManager.initialize(handler, seat_ui=FakeSeatUI(desks=scan))
    # 占座游标：机器人此刻在 desk 5 左位 = 11 号位
    SeatManager.instance()._subsystem.current_desk_index = 5
    SeatManager.instance()._subsystem.current_side = "left"
    controller = SimpleNamespace(soul_handler=handler, music_handler=None, logger=handler.logger)
    return obs, handler, controller


@pytest.mark.asyncio
async def test_stale_owner_render_of_released_seat_does_not_resurrect_the_bot():
    obs, handler, controller = _setup_relocation()

    result = await SeatCommand(controller).process(MessageInfo(content=":seat", nickname="Chainer"), [])
    assert "error" not in result, result

    for line in _layout_logs(handler.logger, "视口同步"):
        assert "[11号: 群主" not in line, line

    assert obs.seats[9].occupied and obs.seats[9].username == OWNER
    assert not obs.seats[11].occupied
    assert sum(1 for slot in obs.seats.values() if slot.occupied and slot.is_owner) == 1


@pytest.mark.asyncio
async def test_relocation_is_logged_as_a_move():
    obs, handler, controller = _setup_relocation()

    result = await SeatCommand(controller).process(MessageInfo(content=":seat", nickname="Chainer"), [])
    assert "error" not in result, result

    assert any(
        "Bot relocated from seat 11 to seat 9" in line for line in _info_lines(handler.logger)
    ), _info_lines(handler.logger)


@pytest.mark.asyncio
async def test_later_passive_round_does_not_relitigate_the_released_seat():
    obs, handler, controller = _setup_relocation()

    result = await SeatCommand(controller).process(MessageInfo(content=":seat", nickname="Chainer"), [])
    assert "error" not in result, result

    visible_desks = build_live_desk_wrappers_for(handler, {10: "管理", 11: "群主", 12: "管理"}, phase="bottom")
    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await obs.observe_visible_desks(visible_desks, current_focus_count=4)

    assert not obs.seats[11].occupied
    assert obs.seats[9].username == OWNER
