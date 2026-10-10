"""/seat 之后座位快照必须刷新，不能把执行前的旧快照原样打出来。

真机 10-10 17:36:25 的症状：机器人（Outlier，管理）在 desk 1 右位坐下
（日志逐字对得上："Accompanying 管理 at desk 1, right seat"），但紧接着打出的
`[FocusSeatObservation]` 座次表仍是执行前那一版：1/2 号位显示空闲，机器人
还挂在 9 号位，另有早已过期的 3/4 号位读数。同一份数据在 17:42 的 /info 里
继续显示「Joyer(2号)」，而真机截图里群主早已坐到 12 号位。

复现前提：`SeatCommand.process` 的 `finally` 调 `_log_seating_layout`，它只
`format_3row_layout(...)` 内存快照；而 `/seat` 走的 `find_owner_seat ->
_take_seat -> _confirm_seat` 全程不写快照（只有 `:seat 2 <n>` 的
`sit_at_specific_seat` 写了 `mark_owner_seated`）。所以这条路径上的座次表
必然是旧值。
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


@pytest.fixture(autouse=True)
def reset_seat_singletons():
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()


class _ConfirmableFinder(FakeElementFinder):
    """补上 `_confirm_seat` 需要的两个确认件，与 ElementFinder 同名契约。"""

    def wait_for_element_clickable(self, element_key, timeout=10):
        node = SimpleNamespace(text="", clicked=False)
        node.click = lambda: setattr(node, "clicked", True)
        return node


def _make_handler(desks, page_source):
    handler = MagicMock()
    handler.logger = MagicMock()
    handler.config = {"elements": soul_elements()}
    handler.controller = None  # 命令派发链外层才持锁；单测退化不加锁
    handler.element_finder = _ConfirmableFinder(soul_elements(), desks=desks)
    # 快照刷新读的是 driver.page_source —— 与生产同一条取数路径。
    handler.driver = MagicMock()
    handler.driver.page_source = page_source
    return handler


def _layout_logs(logger):
    return [
        str(call[0][0])
        for call in logger.info.call_args_list
        if call[0] and "[FocusSeatObservation] 专注麦位状态变更" in str(call[0][0])
    ]


@pytest.mark.asyncio
async def test_seat_command_layout_log_reflects_the_seat_it_just_took():
    """`/seat` 坐下之后打印的座次表必须反映刚落座的号位。

    桌位布置刻意与真机 10-10 17:36:25 同形：只有 desk 0 的 1 号位坐着一位管理、
    2 号位空着，其余桌位全空。机器人带着 9 号位的旧游标进场，
    `find_owner_seat` 的扫描顺序 [4,5,0,...] 一路跳到 desk 0 的空位，
    `_select_companion_candidate` 挑中右位 —— 正是日志里那句
    "Accompanying 管理 at desk 1, right seat"。
    """
    desks = build_live_raw_desks_for({1: "管理"}, phase="full")
    # 落座后的真机形状读数：机器人已离开 9 号位、落到 2 号位。真机渲染规则见
    # build_live_page_source —— 占座渲染身份文字、空座没有 label 节点，所以全屏
    # 没有任何数字锚点，相位是唯一能把号位对上的依据（band=None 实测读出 0 个号位）。
    page_source = build_live_page_source({1: "管理", 2: "管理"}, phase="full")
    handler = _make_handler(desks, page_source)
    obs = SeatObservationManager.initialize(handler)
    # 执行前的旧快照：机器人在 9 号位，外加两条早已过期的读数
    obs.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Outlier", label="管理")
    obs.seats[3] = SeatSlot(seat_number=3, occupied=True, username="Joyer", is_owner=True)
    obs.seats[4] = SeatSlot(seat_number=4, occupied=True, username="不约儿童🐏🐏", label="管理")

    SeatManager.initialize(handler, seat_ui=FakeSeatUI(desks=desks))
    # 机器人此前占着 9 号位（desk 4 左位）—— 旧位号由这个游标给出，不靠猜身份
    SeatManager.instance()._subsystem.current_desk_index = 4
    SeatManager.instance()._subsystem.current_side = "left"
    controller = SimpleNamespace(
        soul_handler=handler, music_handler=None, logger=handler.logger
    )

    result = await SeatCommand(controller).process(
        MessageInfo(content=":seat", nickname="Outlier"), []
    )

    assert "error" not in result, result

    # 刷新本身是一次真实变更，会先打一条「视口同步」；命令收尾再打一条
    # 「seat命令执行」。用户读的是后者，断言必须落在它身上。
    layouts = [l for l in _layout_logs(handler.logger) if "触发源: seat命令执行" in l]
    assert len(layouts) == 1, _layout_logs(handler.logger)
    layout = layouts[0]

    # 刚落座的 2 号位必须在座次表里；9 号位滚出了视口（观测层不推平看不见的位），
    # 由占座游标显式腾空 —— 两条合起来才是「1/2 号位已更新」的真机事实。
    assert "[2号: 空闲]" not in layout, layout
    assert "[9号: 空闲]" in layout, layout
    # 视口内的过期读数必须被真实界面推平，而不是留着执行前那一版
    assert "Joyer" not in layout, layout
    assert "不约儿童" not in layout, layout
