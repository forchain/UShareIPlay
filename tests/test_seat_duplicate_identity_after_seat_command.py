"""`:seat` 之后快照里不能出现同一人占两座 —— 真机 10-10 18:46–18:48 的「4/11 两个 Chainer」。

真机日志逐字：

    18:47:57 _take_seat:934 - Accompanying 4 at desk 2, left seat
    18:47:59 sync_current_viewport:2270 - ... 4号: 已占用        <- 视口同步直接落了个无名占座
    18:47:59 _log_seating_layout:33 - ... 3号: 群主(Joyer) [4号: 已占用]
    18:48:04 inspect_occupant:1052 - Inspecting occupant on seat 4 (right side)
    18:48:05 _sync_desks:1751 - ... [4号: 管理(Chainer)] ... [11号: 管理(Chainer)]

4 号位与 11 号位同时写着 Chainer，座次表 6 人对着同一行里的专注 5 人。一个人同一
时刻只占一个座位，所以这份快照自相矛盾，而且它对账闸门（`_reconcile_focus_count`
只在专注人数**取值变化**时重扫）不会发现 —— 差额要等下次有人进出专注才有机会被查。

机理：`/seat` 落座后的视口重读（`_refresh_snapshot_after_seating` ->
`sync_current_viewport`）**不走** `_plan_observation_changes` 的去向闸，直接把视口里
「占座但身份未知」的新占位写进快照；下一轮被动观测才点头像读出身份，而这时
「这个人是不是刚从看不见的位子换过来」的判据（`appears` + 别处已占座）因为快照里
这个位子**已经**是占座态而被跳过（`old.username is None` 走的是 `writable` 分支），
于是同一个名字被写进第二个号位。11 号位不在视口里，谁都不会去清它。
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
MOVER = "Chainer"

# 房间里「真」的占座情况（18:47:5x，Chainer 已从 11 号位换到 4 号位）：
# 9/10/12 号位各一人，群主 Joyer 刚坐下、11 号位空着。4 号位渲染的是**过期的**
# 空座编号（面板只重绘了 ClState，TvLabelH 还停在「点击入座」那版），所以读出来
# 是数字 label「4」——普通占座者的昵称本来也不在麦位 DOM 里，只能点头像弹窗。
ROOM_TRUTH = {3: "群主", 4: True, 9: "Outlier", 10: "管理", 12: "管理"}


def _layout_logs(logger, trigger_source=None):
    return [
        str(call[0][0])
        for call in logger.info.call_args_list
        if call[0]
        and "[FocusSeatObservation] 专注麦位状态变更" in str(call[0][0])
        and (trigger_source is None or f"触发源: {trigger_source}" in str(call[0][0]))
    ]


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


def _make_handler(desks, page_source):
    handler = MagicMock()
    handler.logger = MagicMock()
    handler.config = {"elements": soul_elements(), "room_owner": OWNER}
    handler.controller = None  # 命令派发链外层才持锁；单测退化不加锁
    handler.element_finder = _ConfirmableFinder(soul_elements(), desks=desks)
    handler.gesture_handler = MagicMock()
    handler.driver = MagicMock()
    handler.driver.page_source = page_source
    return handler


def _seed_room(obs):
    """真机 18:46:58 那版快照：群主在 2 号位，9/10/11/12 各一人，专注 5 人。"""
    obs.seats[2] = SeatSlot(seat_number=2, occupied=True, username=OWNER, label="群主", is_owner=True)
    obs.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Outlier", label="9")
    obs.seats[10] = SeatSlot(seat_number=10, occupied=True, username="不约儿童🐏🐏", label="管理")
    obs.seats[11] = SeatSlot(seat_number=11, occupied=True, username=MOVER, label="管理")
    obs.seats[12] = SeatSlot(seat_number=12, occupied=True, username="儿童不易~🐏🐏", label="管理")
    obs._last_focus_count = 5
    obs._reconciled_focus_count = 5


@pytest.mark.asyncio
async def test_seat_command_does_not_leave_the_mover_on_two_seats():
    """换座者（11 → 4）只能出现在一个号位上，在座数必须等于专注人数。"""
    # 落座前机器人的扫描视角：群主在 2 号位、4 号位已有占座者（渲染成空座编号「4」）
    scan_desks = build_live_raw_desks_for({2: "群主", 4: True, 9: "Outlier", 10: "管理", 11: "管理", 12: "管理"}, phase="full")
    # 落座后的视口重读：机器人的新 3 号位还没重绘（仍渲染成空座），4 号位读成占座但无名
    page_source = build_live_page_source({2: "群主", 4: True, 9: "Outlier", 10: "管理", 12: "管理"}, phase="top")
    handler = _make_handler(scan_desks, page_source)

    obs = SeatObservationManager.initialize(handler)
    _seed_room(obs)

    seat_ui = FakeSeatUI(desks=scan_desks)
    obs._seat_ui = seat_ui
    SeatManager.initialize(handler, seat_ui=seat_ui)
    # 占座游标：机器人此刻在 2 号位（desk 0 右位）
    SeatManager.instance()._subsystem.current_desk_index = 0
    SeatManager.instance()._subsystem.current_side = "right"
    controller = SimpleNamespace(soul_handler=handler, music_handler=None, logger=handler.logger)

    result = await SeatCommand(controller).process(
        MessageInfo(content=":seat", nickname=MOVER), []
    )
    assert "error" not in result, result

    # 落座后那次视口重读把 4 号位直接写成「占座但无名」（真机 18:47:59 的 4号: 已占用）
    sync_layouts = _layout_logs(handler.logger, "视口同步")
    assert sync_layouts, "落座后应有一次视口重读落账"
    assert "[4号: 已占用]" in sync_layouts[0], sync_layouts[0]

    # 下一轮被动观测：面板此时已重绘（机器人的 3 号位、4 号位的占座者都在这一屏上，
    # 11 号位空着），4 号位的头像弹窗读出来正是刚换座的 Chainer（真机 18:48:04）。
    # 展开重扫读的是面板当时的样子，所以两份替身都换成重绘后的真机读数。
    truth_desks = build_live_raw_desks_for(ROOM_TRUTH, phase="full")
    handler.element_finder.desks = truth_desks
    seat_ui.desks = truth_desks
    handler.element_finder.popup_name = MOVER
    visible_desks = build_live_desk_wrappers_for(handler, ROOM_TRUTH, phase="top")
    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await obs.observe_visible_desks(visible_desks, current_focus_count=5)

    # 去向不明的那条读数不许静默落账：必须交给全量重扫定夺
    rescan_layouts = _layout_logs(handler.logger, "专注人数背离展开重扫")
    assert rescan_layouts, "别处已占座的同名读数必须升级为全量重扫"
    assert "[11号: 空闲]" in rescan_layouts[-1], rescan_layouts[-1]

    # 一个人只能占一个座位：换座者的新位子认下来了，旧位子就不该还挂着他
    holders = {num: slot.username for num, slot in obs.seats.items() if slot.occupied}
    assert sorted(holders.values()) == sorted(set(holders.values())), holders
    assert obs.seats[4].username == MOVER, holders
    assert not obs.seats[11].occupied, holders

    # 在座人数必须与专注人数一致（真机的「专注数 5 vs 座次表 6」）
    seated = sum(1 for slot in obs.seats.values() if slot.occupied)
    assert seated == 5, (seated, holders)
