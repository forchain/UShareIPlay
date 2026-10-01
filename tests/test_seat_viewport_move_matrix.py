"""可视范围内换座的检测矩阵：视口相位 × 换座方向 × 残留渲染 × :seat 命令。

为什么需要矩阵（真机 09-29 11:40:5x / 09-28 21:33:57）：麦位换座在 DOM 上不是一个
事件，而是"某一屏读数变了"。这一屏能看到什么，完全由面板的展开状态与滚动位置决定：

| 视口相位            | 能读到座位号吗 | 换座的可观测形状                         |
|---------------------|----------------|------------------------------------------|
| expanded top(1~8)   | 能（编号 label）| 旧位变空、新位读成"占座但没昵称"          |
| expanded bottom(5~12)| 能             | 同上，但覆盖 9~12 号位                    |
| collapsed top       | **不能**（群主/管理占座渲染身份文字，空座根本没有 label 节点）| 整屏身份未知，只能靠麦位带内容指纹 |
| collapsed bottom    | 看运气         | 同上                                     |

而普通用户的昵称**不在麦位 DOM 里**（真机 dump：占座 = ClState + 麦位编号 label +
勋章 + 专注时长），唯一的身份手段是点头像读弹窗。所以"换座没检测到"从来不是单点
bug，而是这条证据链上任何一环把本轮证据判输给了上一轮账面值。

这里把三件事钉成矩阵：
1. 夹具生成器的 DOM 语义必须与真机 dump 一致（防止测试自造一套现实）；
2. 每个相位里的可视换座都不许被静默吞掉（要么落快照，要么升级为全量重扫）；
3. 组合 :seat 命令（换座 + 观测 + 重扫）之后，账本必须收敛到真实座次。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lxml import etree

from tests.seat_fixtures import (
    FakeSeatUI,
    LIVE_VIEWPORT_PHASES,
    build_live_desk_wrappers_for,
    build_live_page_source,
    build_live_raw_desks_for,
    live_seat_bounds,
    load_real_desk_nodes,
    make_handler,
    DESK_RESOURCE_ID,
)
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)
from ushareiplay.managers.seat_manager.seating import SeatingManager

MOVER = "Outlier"

# 每个相位里"完整渲染、且座位号可锚定"的麦位集合（desk 序号 × 2 + 1/2）
PHASE_SEATS = {
    phase: {
        desk * 2 + offset
        for desk in desks
        for offset in (1, 2)
    }
    for phase, (desks, _fragments) in LIVE_VIEWPORT_PHASES.items()
}


@pytest.fixture(autouse=True)
def reset_observation():
    SeatObservationManager.reset_instance()
    SeatingManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()
    SeatingManager.reset_instance()


# --------------------------------------------------------------------------
# 1. 夹具保真度：生成器造出来的必须就是真机那一屏
# --------------------------------------------------------------------------


def test_generated_empty_seat_matches_real_dump_reads_as_empty_not_occupied():
    """真机空座：1 张占位图 + 「点击入座」，没有 ClState、没有 label 节点。

    生成器要是把空座画成"编号 label 的空座"，整个矩阵就会测在一个真机上不存在的
    形状上（这正是换座漏检被掩盖的原因：测试用 label=昵称 的桌位，跳过了
    "占座读不出身份"这条真机主路径）。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    real_desks = [node for node in load_real_desk_nodes("expanded_top_with_anchor.xml")]
    from ushareiplay.core.element_wrapper import ElementWrapper

    # 真机：1 号位群主占座（ClState + 身份文字 + 勋章 + 时长），2 号位空座
    real_left = ElementWrapper(real_desks[0], handler, "seat_desk")
    real_owner = manager._extract_seat_info(real_left, "left", 1)
    real_empty = manager._extract_seat_info(real_left, "right", 2)
    assert (real_owner["occupied"], real_owner["label"]) == (True, "群主")
    assert (real_empty["occupied"], real_empty["is_empty"]) == (False, True)

    # 生成器：同一套判据下必须给出同样的读数
    generated = build_live_desk_wrappers_for(handler, {1: "群主"}, "top")[0]
    gen_owner = manager._extract_seat_info(generated, "left", 1)
    gen_empty = manager._extract_seat_info(generated, "right", 2)
    assert (gen_owner["occupied"], gen_owner["label"]) == (True, "群主")
    assert (gen_empty["occupied"], gen_empty["is_empty"]) == (False, True)


def test_generated_normal_occupant_has_no_nickname_in_dom():
    """真机普通用户占座：ClState + **麦位编号** label，昵称读不出来。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    desk = build_live_desk_wrappers_for(handler, {11: True}, "bottom")[-1]

    info = manager._extract_seat_info(desk, "left", 11)

    assert info["occupied"] is True
    assert info["username"] is None, "普通用户昵称不在麦位 DOM 里"
    assert info["label"] == "11"


def test_collapsed_top_phase_has_no_seat_number_anchor():
    """折叠顶视口读不出任何座位号：这就是"只能靠内容指纹兜底"的那个相位。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    desks = build_live_desk_wrappers_for(handler, {1: "群主"}, "collapsed_top")

    assert manager._read_visible_seats(desks) == {}


# --------------------------------------------------------------------------
# 2. 换座检测矩阵：任何相位里的可视换座都不许被静默吞掉
# --------------------------------------------------------------------------


def _settle(manager, occupants, phase, focus_count):
    """先按"换座前"的那一屏跑一轮，把快照与麦位带基线都落到起点。"""
    desks = build_live_desk_wrappers_for(manager.handler, occupants, phase)
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as scan:
        scan.return_value = True
        return asyncio_round(manager, desks, focus_count)


async def asyncio_round(manager, desks, focus_count):
    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        return await manager.observe_visible_desks(desks, current_focus_count=focus_count)


def _manager_with_snapshot(occupants, names):
    """按 occupants 建快照：普通用户占座的昵称只有弹窗给得出，测试直接写进账面。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    for seat, occupant in occupants.items():
        username = names.get(seat)
        manager.seats[seat] = SeatSlot(
            seat_number=seat,
            occupied=True,
            username=username,
            label=username or str(seat),
            is_owner=username == "群主",
        )
    return manager


MOVES = [
    # (相位, 旧位子, 新位子) —— 两端都在同一屏里，纯"可视范围内换位"
    ("top", 2, 3),
    ("top", 4, 1),
    ("top", 6, 5),
    ("top", 8, 7),
    ("bottom", 12, 11),
    ("bottom", 9, 10),
    ("bottom", 5, 6),
    ("bottom", 7, 8),
]


@pytest.mark.parametrize("phase,src,dst", MOVES)
@pytest.mark.parametrize("residual", [True, False], ids=["residual", "repainted"])
@pytest.mark.asyncio
async def test_in_viewport_move_is_never_swallowed_any_phase(phase, src, dst, residual):
    """每个相位的可视换座：要么本轮就落快照，要么升级为全量重扫，绝不许原地不动。

    residual=True 是真机上更糟的那一半：旧位子换座后仍渲染成占座（残留渲染），
    本轮读不到它的身份，只有快照里挂着这个人 —— 旧实现正是拿这条账面残留去否定
    新位子的弹窗证据，把换座整个吞掉。
    """
    before = {src: True}
    manager = _manager_with_snapshot(before, {src: MOVER})
    manager._last_focus_count = 1
    manager._reconciled_focus_count = 1  # 关掉人数对账这条触发源，只看变更检测

    after = {dst: True}
    if residual:
        after[src] = True

    # 弹窗是唯一能认出人的手段：真实落座处与残留渲染都指向同一个人
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: MOVER if seat_number == dst else None
    )

    desks = build_live_desk_wrappers_for(manager.handler, after, phase)
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as scan:
        scan.return_value = True
        with patch(
            "ushareiplay.managers.command_manager.CommandManager.instance"
        ) as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            await manager.observe_visible_desks(desks, current_focus_count=1)

    applied = manager.seats[dst].occupied and manager.seats[dst].username == MOVER
    vacated = not manager.seats[src].occupied
    escalated = scan.await_count >= 1
    assert applied or escalated, (
        f"{phase} 相位 {src}->{dst}（residual={residual}）被静默吞掉："
        f"快照仍是 {manager.seats[src].username}@{src} / "
        f"{manager.seats[dst].username}@{dst}，也没有升级为全量重扫"
    )
    if applied:
        assert vacated, f"换座落账必须腾出旧位子：{src} 仍记为在座"


@pytest.mark.parametrize("phase,src,dst", MOVES)
@pytest.mark.asyncio
async def test_full_rescan_converges_an_in_viewport_move(phase, src, dst):
    """权威重扫必须收敛到真实座次：新位子在座、旧位子腾出、且报出 move_seat。

    重扫读的是全部三排（顶相位 + 底相位），是唯一能替被动观测下结论的路径。
    """
    before = {src: True}
    manager = _manager_with_snapshot(before, {src: MOVER})
    manager._last_focus_count = 1

    # 旧位子还渲染成占座（残留渲染），新位子是真实落座处
    desks = build_live_raw_desks_for({dst: True, src: True}, "full")
    handler = manager.handler
    handler.element_finder.find_elements = MagicMock(return_value=desks)
    manager._seat_ui = FakeSeatUI(desks=desks)
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: MOVER if seat_number == dst else None
    )

    with patch(
        "ushareiplay.managers.command_manager.CommandManager.instance"
    ) as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.expand_rescan_and_collapse(1)

    assert manager._last_rescan_ok is True
    assert changed is True, f"{phase}: {src}->{dst} 换座在权威重扫里也没被认出来"
    assert manager.seats[dst].username == MOVER
    assert manager.seats[src].occupied is False
    assert notify.call_args.kwargs["seat_info"][MOVER] == {
        "seat_number": dst,
        "action": "move_seat",
    }
    assert sum(1 for slot in manager.seats.values() if slot.occupied) == 1, "一人一麦位"


@pytest.mark.asyncio
async def test_anchor_losing_move_is_still_detected_in_an_unreadable_phase():
    """换座把唯一的编号 label 一起带走、下一轮整屏读不出身份时，也必须检测到。

    折叠顶视口里只有群主（label 是身份文字）与 Outlier（label 是编号 2）。Outlier
    挪出这一屏之后，屏上再没有任何数字锚点 —— 整轮读数进不了快照。旧实现只在
    "身份未知"的轮次维护指纹基线，身份可解析的轮次会把基线清空，于是变更恰好发生
    在那一轮时永远没有可比对象，漏检。
    """
    handler = make_handler()
    handler.config["room_owner"] = "Joyer"  # 「群主」身份文字要归一成房主昵称本人
    manager = SeatObservationManager.initialize(handler)
    manager.seats[1] = SeatSlot(1, occupied=True, username="Joyer", label="群主", is_owner=True)
    manager.seats[2] = SeatSlot(seat_number=2, occupied=True, username=MOVER, label="2")
    manager._last_focus_count = 2
    manager._reconciled_focus_count = 2
    manager.inspect_occupant = AsyncMock(return_value=None)

    readable = build_live_desk_wrappers_for(handler, {1: "群主", 2: True}, "collapsed_top")
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as scan:
        scan.return_value = True
        await manager.observe_visible_desks(readable, current_focus_count=2)
    assert scan.await_count == 0, "起点轮不该触发重扫"

    # Outlier 挪到这一屏之外的 12 号位：顶视口只剩群主，读不出任何座位号
    unreadable = build_live_desk_wrappers_for(handler, {1: "群主", 12: True}, "collapsed_top")
    assert manager._read_visible_seats(unreadable) == {}, "前提：这一轮身份未知"
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as scan:
        scan.return_value = True
        await manager.observe_visible_desks(unreadable, current_focus_count=2)

    assert scan.await_count == 1, "锚点随人消失的那一轮换座被漏掉了"
    assert "identity is unknown" in scan.await_args.kwargs["reason"]


# --------------------------------------------------------------------------
# 3. 组合 :seat 命令：换座 + 视口同步 + 观测，账本不许打架
# --------------------------------------------------------------------------


@pytest.mark.parametrize("seat_number", sorted({s for seats in PHASE_SEATS.values() for s in seats}))
@pytest.mark.asyncio
async def test_take_seat_command_clicks_the_requested_seat_in_every_phase(seat_number):
    """:seat 2 <n> 对 1~12 每个号位都要点到那一个麦位，并且只更新那一个位子。"""
    desk_index = (seat_number - 1) // 2
    phase = "top" if desk_index <= 3 else "bottom"
    home = 1 if seat_number != 1 else 2
    handler = make_handler()
    handler.driver = MagicMock()
    # 目标位子在屏上但是空的，房主原本坐在另一个位子上
    handler.driver.page_source = build_live_page_source({home: "群主"}, phase)

    observation = SeatObservationManager.initialize(handler)
    observation._last_focus_count = 1
    observation.seats[home] = SeatSlot(home, occupied=True, username="Joyer", label="群主", is_owner=True)
    seat_ui = FakeSeatUI(desks=[MagicMock() for _ in range(6)])
    seating = SeatingManager.initialize(handler=handler, seat_ui=seat_ui, observation=observation)
    handler.element_finder.wait_for_element_clickable = MagicMock(
        side_effect=lambda key, **kwargs: MagicMock() if key == "confirm_seat" else None
    )

    result = await seating.sit_at_specific_seat(seat_number)

    assert result == {"success": "Successfully took a seat"}
    click_x, click_y = handler.gesture_handler.click_at.call_args.args
    target = live_seat_bounds(seat_number)
    assert target["x"] <= click_x <= target["x"] + target["width"]
    assert target["y"] <= click_y <= target["y"] + target["height"]
    assert observation.seats[seat_number].is_owner is True
    assert observation.seats[home].occupied is False, "换座必须腾出房主原来的位子"


@pytest.mark.asyncio
async def test_seat_command_then_other_users_in_viewport_move_is_detected():
    """组合场景：房主 :seat 换座之后，别人在同一屏里换座必须还能被检测出来。

    真机 09-29 11:41:3x 的形状就是"刚跑完视口同步，紧接着别人的可视换座"——
    视口同步会把快照改写成自己那份读数，不能把随后那次变更的判定资格一起改掉。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.seats[1] = SeatSlot(1, occupied=True, username="Joyer", label="群主", is_owner=True)
    manager.seats[2] = SeatSlot(2, occupied=True, username=MOVER, label="2")
    manager._last_focus_count = 2
    manager._reconciled_focus_count = 2

    # 房主换到 3 号位：视口同步（顶相位，1~8 号位在屏上）
    handler.driver = MagicMock()
    handler.driver.page_source = build_live_page_source({2: True, 3: "群主"}, "top")
    await manager.sync_current_viewport(band="top")
    assert manager.seats[3].occupied is True
    assert manager.seats[1].occupied is False

    # 紧接着 Outlier 在 2 号 -> 4 号（同一屏，旧位残留渲染）
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: MOVER if seat_number == 4 else None
    )
    desks = build_live_desk_wrappers_for(
        manager.handler, {3: "群主", 2: True, 4: True}, "top"
    )
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as scan:
        scan.return_value = True
        with patch(
            "ushareiplay.managers.command_manager.CommandManager.instance"
        ) as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            await manager.observe_visible_desks(desks, current_focus_count=2)

    detected = manager.seats[4].username == MOVER or scan.await_count >= 1
    assert detected, "视口同步之后的可视换座被吞掉了"


# --------------------------------------------------------------------------
# 4. 稳定性：残留渲染不许把账本在两个位子之间来回掀翻
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persistent_residual_render_does_not_flip_the_ledger_back():
    """换座提交后，旧位子连续几轮仍渲染成占座时，答案必须保持稳定。

    "本轮弹窗证据优先于上一轮沿用值"这条规则本身是对称的：一旦提交，下一轮的
    "沿用值"就换到了新位子上，光靠证据来路判，每次重扫都会把人选到另一个位子，
    账本在 11/12 之间来回掀翻，并且每轮都引爆一次展开重扫。收敛靠的是把已确认的
    残留渲染记下来（_residual_seats），下一轮拿它去比，而不是重新猜。
    """
    handler = make_handler()
    manager = _manager_with_snapshot({12: True}, {12: MOVER})
    manager._last_focus_count = 1
    manager._reconciled_focus_count = 1
    # 残留渲染点开头像读出的还是同一个人（真机 09-28 18:07 就是这个形状）
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: MOVER if seat_number in (11, 12) else None
    )
    desks = build_live_desk_wrappers_for(handler, {11: True, 12: True}, "bottom")

    # 第一轮：检出换座并升级为全量重扫；重扫按真机形状收敛到 11 号位
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as scan:
        scan.return_value = True
        await manager.observe_visible_desks(desks, current_focus_count=1)
    assert scan.await_count == 1
    raw = build_live_raw_desks_for({11: True, 12: True}, "full")
    handler.element_finder.find_elements = MagicMock(return_value=raw)
    manager._seat_ui = FakeSeatUI(desks=raw)
    with patch(
        "ushareiplay.managers.command_manager.CommandManager.instance"
    ) as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.expand_rescan_and_collapse(1)
    assert manager.seats[11].username == MOVER
    assert manager.seats[12].occupied is False

    # 之后同样的两屏读数连续再来三轮：位子不许换、也不许再触发重扫
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as scan:
        scan.return_value = True
        for _ in range(3):
            await manager.observe_visible_desks(desks, current_focus_count=1)
    assert scan.await_count == 0, "残留渲染反复抢身份，账本被掀翻"
    assert manager.seats[11].username == MOVER
    assert manager.seats[12].occupied is False
    assert sum(1 for slot in manager.seats.values() if slot.occupied) == 1

    # 面板终于重绘：旧位子读成空座，残留记录作废，一切照旧
    repainted = build_live_desk_wrappers_for(handler, {11: True}, "bottom")
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as scan:
        scan.return_value = True
        await manager.observe_visible_desks(repainted, current_focus_count=1)
    assert scan.await_count == 0
    assert manager._residual_seats.get(12) is None
    assert manager.seats[11].username == MOVER


@pytest.mark.asyncio
async def test_new_occupant_sitting_on_a_known_residual_seat_is_not_lost():
    """残留位上真坐了别人：弹窗认出的是另一个人，残留记录必须当场作废。"""
    handler = make_handler()
    manager = _manager_with_snapshot({11: True}, {11: MOVER})
    manager._last_focus_count = 2
    manager._reconciled_focus_count = 2
    manager._residual_seats = {12: MOVER}  # 上一轮确认过的残留
    newcomer = "Chainer"
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: newcomer if seat_number == 12 else None
    )

    desks = build_live_desk_wrappers_for(handler, {11: True, 12: True}, "bottom")
    with patch(
        "ushareiplay.managers.command_manager.CommandManager.instance"
    ) as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.observe_visible_desks(desks, current_focus_count=2)

    assert manager.seats[12].username == newcomer, "残留记录把新落座的人吞掉了"
    assert manager._residual_seats.get(12) is None


@pytest.mark.asyncio
async def test_person_moving_back_onto_a_recorded_residual_seat_is_not_erased():
    """残留记录不许把人从账上抹掉：他别处已经没有位置时，这里就是真实落座处。

    残留判定天生是"这个人在别处还有位置"的推论。Outlier 从 11 号换回 12 号时，
    11 号读成空座、12 号（上一轮的残留位）读成占座且弹窗还是他 —— 要是继续按
    残留清空 12 号，账上就再没有这个人了。
    """
    handler = make_handler()
    manager = _manager_with_snapshot({11: True}, {11: MOVER})
    manager._last_focus_count = 1
    manager._reconciled_focus_count = 1
    manager._residual_seats = {12: MOVER}  # 上一轮确认：12 号是 Outlier 的残留渲染
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: MOVER if seat_number == 12 else None
    )

    # 11 号已重绘成空座，人坐回了 12 号
    desks = build_live_desk_wrappers_for(handler, {12: True}, "bottom")
    with patch(
        "ushareiplay.managers.command_manager.CommandManager.instance"
    ) as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.observe_visible_desks(desks, current_focus_count=1)

    assert manager._residual_seats.get(12) is None, "残留判定该在别处没位置时当场作废"
    assert manager.seats[12].username == MOVER, "人不能从账上消失"
    assert manager.seats[11].occupied is False
    assert changed is True
    assert notify.call_args.kwargs["seat_info"][MOVER] == {
        "seat_number": 12,
        "action": "move_seat",
    }
