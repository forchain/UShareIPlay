"""/seat 换座后，机器人自己的新号位必须进快照 —— 不能只靠一次可能还没重绘的视口重读。

真机 10-10 18:10:59–18:11:07 的症状：机器的群主（Joyer）坐在 1 号位，另一条
`:seat` 把它转到 desk 6 左位（11 号位，日志逐字对得上："Accompanying 管理 at
desk 6, left seat"）。命令收尾打出的座次表里 **1 号位和 11 号位同时写着空闲**：
旧位被 `release_bot_seat` 按占座游标腾掉了，新位却指望落座后那一次
`sync_current_viewport` 读出来 —— 而那一次重读撞上的是 Soul 还没重绘的界面
（11 号位仍渲染「点击入座」），于是它既没写进快照、也没打「视口同步」
（真机日志里 18:11 这段确实没有视口同步那一行，而 18:10 那次重绘及时就有）。

后果是两条，同源：
1. 座次表查不到机器人 —— 「并没有更新座位」；
2. 快照在座 3 个人、同一行里的专注人数是 4 —— 而对账闸门只在专注人数**取值变化**
   时重扫（`_reconcile_focus_count`），自己造出来的差额要等到下次有人进出专注
   才有机会被发现，错表格会一路用到下一次人数变化为止。

`:seat 2 <n>`（`sit_at_specific_seat`）没有这个问题：它落座成功后直接
`mark_owner_seated(seat_number)`，把游标事实写进快照，不依赖界面重读。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.seat_fixtures import (
    FakeElementFinder,
    FakeSeatUI,
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
OTHER_SEATS = {9: True, 10: "管理", 12: "管理"}


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
    # 真机 config.yaml 的 soul 段：room_owner 决定了「群主」徽章归谁（_owner_nickname）
    handler.config = {"elements": soul_elements(), "room_owner": OWNER}
    handler.controller = None  # 命令派发链外层才持锁；单测退化不加锁
    handler.element_finder = _ConfirmableFinder(soul_elements(), desks=desks)
    handler.gesture_handler = MagicMock()
    handler.driver = MagicMock()
    handler.driver.page_source = page_source
    return handler


def _layout_logs(logger, trigger_source):
    return [
        str(call[0][0])
        for call in logger.info.call_args_list
        if call[0]
        and "[FocusSeatObservation] 专注麦位状态变更" in str(call[0][0])
        and f"触发源: {trigger_source}" in str(call[0][0])
    ]


def _seed_room(obs):
    """真机 18:10:41 那版快照：群主在 1 号位，9/10/12 号位各一人，专注 4 人。"""
    obs.seats[1] = SeatSlot(seat_number=1, occupied=True, username=OWNER, label="群主", is_owner=True)
    obs.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Outlier", label="9")
    obs.seats[10] = SeatSlot(seat_number=10, occupied=True, username="不约儿童🐏🐏", label="管理")
    obs.seats[12] = SeatSlot(seat_number=12, occupied=True, username="儿童不易~🐏🐏", label="管理")
    obs._last_focus_count = 4
    obs._reconciled_focus_count = 4


@pytest.mark.asyncio
async def test_seat_command_records_the_new_seat_when_the_panel_has_not_repainted():
    """机器人从 1 号位换到 11 号位：落座后的座次表必须写着 11 号位是它。

    重读刻意做成真机那一次的样子 —— 面板已滚到底（band="bottom"），但 11 号位
    还渲染成「点击入座」（Soul 尚未重绘），所以这一轮界面读不出任何新信息。
    """
    # 落座前的面板读数：群主在 1 号位，9/10/12 有人，其余空着
    desks = build_live_raw_desks_for({1: "群主", **OTHER_SEATS}, phase="full")
    # 落座后的重读：11 号位仍是空座渲染
    page_source = build_live_page_source(dict(OTHER_SEATS), phase="bottom")
    handler = _make_handler(desks, page_source)

    obs = SeatObservationManager.initialize(handler)
    _seed_room(obs)

    SeatManager.initialize(handler, seat_ui=FakeSeatUI(desks=desks))
    # 占座游标：机器人此刻的号位是 desk 0 左位 = 1 号位（18:10 那次落座留下的）
    SeatManager.instance()._subsystem.current_desk_index = 0
    SeatManager.instance()._subsystem.current_side = "left"
    controller = SimpleNamespace(soul_handler=handler, music_handler=None, logger=handler.logger)

    result = await SeatCommand(controller).process(
        MessageInfo(content=":seat", nickname="Chainer"), []
    )

    assert "error" not in result, result

    layouts = _layout_logs(handler.logger, "seat命令执行")
    assert len(layouts) == 1, layouts
    layout = layouts[0]

    # 症状 1：新号位没进快照 —— 1 号位被腾掉之后，机器人从座次表上消失了
    assert "[11号: 群主(" in layout, layout
    assert "[1号: 空闲]" in layout, layout
    # 症状 2：在座人数与专注人数背离
    seated_nums = sorted(num for num, slot in obs.seats.items() if slot.occupied)
    assert len(seated_nums) == obs._last_focus_count, (seated_nums, obs._last_focus_count)


@pytest.mark.asyncio
async def test_seat_command_relocation_does_not_double_count_or_re_read_wrongly():
    """界面重读赶上了重绘（真机 18:10:41 那次）时，换座依然只能算同一个人位移。

    快照里 1 号位必须腾空、11 号位只有机器人一个，且专注人数不被凭空 +1。
    """
    desks = build_live_raw_desks_for({1: "群主", **OTHER_SEATS}, phase="full")
    page_source = build_live_page_source({11: "群主", **OTHER_SEATS}, phase="bottom")
    handler = _make_handler(desks, page_source)

    obs = SeatObservationManager.initialize(handler)
    _seed_room(obs)

    SeatManager.initialize(handler, seat_ui=FakeSeatUI(desks=desks))
    SeatManager.instance()._subsystem.current_desk_index = 0
    SeatManager.instance()._subsystem.current_side = "left"
    controller = SimpleNamespace(soul_handler=handler, music_handler=None, logger=handler.logger)

    result = await SeatCommand(controller).process(
        MessageInfo(content=":seat", nickname="Chainer"), []
    )

    assert "error" not in result, result

    layout = _layout_logs(handler.logger, "seat命令执行")[0]
    assert "[11号: 群主(" in layout, layout
    assert "[1号: 空闲]" in layout, layout
    assert sum(1 for num, slot in obs.seats.items() if slot.occupied and slot.username == OWNER) == 1
    assert obs._last_focus_count == 4, obs._last_focus_count


@pytest.mark.asyncio
async def test_seat_command_records_the_new_seat_when_the_refresh_reads_nothing():
    """那次重读一个桌位都拿不到时（面板未 dump / 半截屏 / driver 换过），也不能读丢机器人。

    这条不是 18:11 那次的形状，而是它的一般形式：`/seat` 换座路径上，机器人自己的
    号位此前**只**由落座后的那次 `sync_current_viewport` 提供，所以界面读不出东西
    （`observed` 为空）就等于这一号位从没发生过 —— 而旧位子已经按游标腾掉了。
    现在游标事实自己落账，界面重读降级为确认。
    """
    desks = build_live_raw_desks_for({1: "群主", **OTHER_SEATS}, phase="full")
    handler = _make_handler(desks, "<hierarchy></hierarchy>")  # 拿不到任何 seat_desk

    obs = SeatObservationManager.initialize(handler)
    _seed_room(obs)

    SeatManager.initialize(handler, seat_ui=FakeSeatUI(desks=desks))
    SeatManager.instance()._subsystem.current_desk_index = 0
    SeatManager.instance()._subsystem.current_side = "left"
    controller = SimpleNamespace(soul_handler=handler, music_handler=None, logger=handler.logger)

    result = await SeatCommand(controller).process(
        MessageInfo(content=":seat", nickname="Chainer"), []
    )
    assert "error" not in result, result

    layout = _layout_logs(handler.logger, "seat命令执行")[0]
    assert "[11号: 群主(" in layout, layout
    assert "[1号: 空闲]" in layout, layout
    # 瞎掉的一轮不该顺手把人数改坏：位移不改人头
    assert obs._last_focus_count == 4, obs._last_focus_count
    assert not _layout_logs(handler.logger, "视口同步"), "读不出东西时不该假称视口有变更"
