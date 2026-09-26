"""座位被动观测的测试。

替身定义在 tests/seat_fixtures.py —— 刻意与生产协作者同形（见 PR #339 review 的
C1/C2）：desk 是真 ElementWrapper，raw WebElement 路径走 find_element 契约，
controller 用真实的 ui_session 异步上下文管理器。
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.seat_fixtures import (
    ClickableNode,
    FakeController,
    FakeSeatUI,
    RawSeatDesk,
    build_desk_wrapper,
    make_handler,
    soul_elements,
)
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)


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

    assert "[FocusSeatObservation] 专注麦位状态变更 (触发源: 测试触发, 专注人数: 未知):" in lines[0]
    assert "第一排: [1号: 群主] [2号: 空闲]  |  [3号: 张三] [4号: 空闲]" in lines[1]
    assert "第二排: [5号: 空闲] [6号: 空闲]  |  [7号: 李四] [8号: 空闲]" in lines[2]
    assert "第三排: [9号: 空闲] [10号: 空闲]  |  [11号: 王五] [12号: 空闲]" in lines[3]


def test_map_desks_to_indices_by_number_labels():
    manager = SeatObservationManager.initialize(make_handler())
    desk_row0_left = build_desk_wrapper(manager.handler, left="1", right="2", y=100)
    desk_row1_right = build_desk_wrapper(manager.handler, left="7", right="8", y=300)
    desk_row2_left = build_desk_wrapper(manager.handler, left="9", right="10", y=500)

    mapped = manager.map_desks_to_indices([desk_row1_right, desk_row0_left, desk_row2_left])

    assert [idx for idx, _ in mapped] == [0, 3, 4]


def test_map_desks_to_indices_without_any_anchor_maps_nothing():
    """身份未知不猜：整条带位都读不到麦位编号时，绝不按坐标顺序硬排座位号。

    旧实现会从 desk 0 起往后排（[0,1,2,3]）—— 面板只露出中后排时整条带位被
    错配两个桌位，第二排的空座读数就被写进 1~4 号位。
    """
    manager = SeatObservationManager.initialize(make_handler())
    desks = [
        build_desk_wrapper(manager.handler, left="群主", right="A", y=500),
        build_desk_wrapper(manager.handler, left="B", right="C", y=100),
        build_desk_wrapper(manager.handler, left="D", right="E", y=300),
        build_desk_wrapper(manager.handler, left="F", right="G", y=200),
    ]

    assert manager.map_desks_to_indices(desks) == []


def test_anchor_pins_band_offset_for_desks_without_seat_numbers():
    """同一视口里只要有一张桌位读到编号，整条带位就能对上正确座位号。

    只露出第二排且左侧桌位全是昵称（读不到编号）时，右侧桌位读到的 7 号空位把
    整个带位的偏移钉在 2：左侧桌位仍落在 desk 2（5/6 号位），不会被排到 0 号位。
    """
    manager = SeatObservationManager.initialize(make_handler())
    desk_without_numbers = build_desk_wrapper(
        manager.handler,
        left="锦鲤",
        right="儿童不易",
        left_occupied=True,
        right_occupied=True,
        bounds="[40,611][400,771]",
    )
    desk_with_seat_numbers = build_desk_wrapper(
        manager.handler, left="7", right="8", bounds="[383,611][743,771]"
    )

    mapped = manager.map_desks_to_indices([desk_without_numbers, desk_with_seat_numbers])

    assert [idx for idx, _ in mapped] == [2, 3]


def test_nickname_digits_do_not_anchor_seat_number():
    manager = SeatObservationManager.initialize(make_handler())

    # 昵称里带数字不算编号
    assert manager._detect_desk_index_from_labels(
        build_desk_wrapper(manager.handler, left="小明7")
    ) is None
    # 左位只可能是奇数号，读到 8 判为昵称
    assert manager._detect_desk_index_from_labels(
        build_desk_wrapper(manager.handler, left="8")
    ) is None
    # 两侧都是数字时必须构成一张桌子：7 配 9、7 配 4 都不成立
    assert manager._detect_desk_index_from_labels(
        build_desk_wrapper(manager.handler, left="7", right="9")
    ) is None
    assert manager._detect_desk_index_from_labels(
        build_desk_wrapper(manager.handler, left="7", right="4")
    ) is None
    # 配对一致才锚定
    assert manager._detect_desk_index_from_labels(
        build_desk_wrapper(manager.handler, left="7", right="8")
    ) == 3
    # 另一侧是昵称时，单侧读到编号也锚定
    assert manager._detect_desk_index_from_labels(
        build_desk_wrapper(manager.handler, left="1", right="小明")
    ) == 0


@pytest.mark.asyncio
async def test_observe_visible_desks_reads_occupancy_from_page_source():
    """C1 回归：desk 是 ElementWrapper 时也必须读到真实占用状态。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value=None)

    desks = [
        build_desk_wrapper(handler, left="群主", right="2", left_occupied=True, y=100),
        build_desk_wrapper(handler, left="3", right="4", y=300),
    ]

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.observe_visible_desks(desks, current_focus_count=1)

    assert changed is True
    assert manager.seats[1].occupied is True
    assert manager.seats[1].is_owner is True
    assert manager.seats[1].username == "群主"
    assert manager.seats[2].occupied is False
    assert manager.seats[3].occupied is False and manager.seats[4].occupied is False

    # 昵称/群主直接可读，不需要点头像弹窗
    manager.inspect_occupant.assert_not_awaited()
    notify.assert_awaited_once()
    kwargs = notify.call_args.kwargs
    assert kwargs["changed_users"] == ["群主"]
    assert kwargs["seat_info"]["群主"] == {"seat_number": 1, "action": "sit_down"}


@pytest.mark.asyncio
async def test_observe_visible_desks_inspects_unknown_occupant_under_ui_session():
    controller = FakeController()
    handler = make_handler(popup_name="Bob", controller=controller)
    manager = SeatObservationManager.initialize(handler)
    lock_states = []
    handler.element_finder.on_wait = lambda: lock_states.append(controller.ui_lock.locked())

    desk = build_desk_wrapper(handler, left="管理", right="2", left_occupied=True)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.observe_visible_desks([desk])

    assert manager.seats[1].username == "Bob"
    # 点头像读弹窗必须持有 ui_session，否则命令任务与兜底 press_back 会踩进来
    assert lock_states and all(lock_states)
    assert controller.sessions == ["seat_inspect"]
    assert controller.ui_lock.locked() is False
    # ElementWrapper 的子元素没有 element key，click() 拿不到真实元素 -> 按坐标点
    assert handler.gesture_handler.click_at.call_args.args == (130, 180)
    handler.key_actions.press_back.assert_called()


@pytest.mark.asyncio
async def test_observe_visible_desks_reuses_known_occupant_without_reinspection():
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value=None)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="张三")

    # 占位者仍是 张三，但这一轮 label 只给到 "管理"（读不到昵称）
    desk = build_desk_wrapper(handler, left="管理", right="2", left_occupied=True)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        await manager.observe_visible_desks([desk])

    assert manager.seats[1].username == "张三"
    manager.inspect_occupant.assert_not_awaited()
    notify.assert_not_awaited()  # 无变化，不发通知


@pytest.mark.asyncio
async def test_same_seat_occupant_swap_escalates_to_full_rescan():
    """同位换人：旧人去向、新人来路都不知道 → 不写快照，全量扫描一遍取最新信息。

    （旧实现会把「李四坐 1 号」直接写进快照并给张三发一条假的离座事件。）
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value=None)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="张三", label="张三")

    desk = build_desk_wrapper(handler, left="李四", right="2", left_occupied=True)

    async def _landed_scan(*_args, **_kwargs):
        manager._last_rescan_ok = True
        return True

    with patch.object(
        manager, "expand_rescan_and_collapse", new_callable=AsyncMock, side_effect=_landed_scan
    ) as mock_rescan:
        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            notify = AsyncMock()
            cmd_mgr.return_value.notify_focus_count_change = notify
            changed = await manager.observe_visible_desks([desk])

    # 快照保持原值等全量扫描给结论，也不发任何座位变更通知
    assert changed is False
    assert manager.seats[1].occupied is True
    assert manager.seats[1].username == "张三"
    notify.assert_not_awaited()
    mock_rescan.assert_awaited_once()


@pytest.mark.asyncio
async def test_relocating_user_reports_move_seat():
    """R3：同一次观测里离开又落座 = move_seat（PR 文档承诺的三个动作之一）。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value=None)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="张三", label="张三")

    desks = [
        # desk 0（1/2 号位）已空
        build_desk_wrapper(handler, left="1", right="2", y=100),
        # desk 1（3/4 号位）坐着 张三
        build_desk_wrapper(handler, left="张三", right="4", left_occupied=True, y=300),
    ]

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        await manager.observe_visible_desks(desks)

    kwargs = notify.call_args.kwargs
    assert kwargs["changed_users"] == ["张三"]
    assert kwargs["seat_info"]["张三"] == {"seat_number": 3, "action": "move_seat"}


def _raw_desk(left_label, right_label, y):
    """展开重扫路径的 desk（raw WebElement）：占用由 left_state 是否存在决定。"""
    elements = soul_elements()
    children = {
        elements["left_label"]: SimpleNamespace(text=left_label),
        elements["right_label"]: SimpleNamespace(text=right_label),
    }
    if left_label:
        children[elements["left_state"]] = SimpleNamespace(text="")
    return RawSeatDesk(children, location={"x": 40, "y": y})


@pytest.mark.asyncio
async def test_focus_divergence_triggers_active_expansion_and_collapse():
    raw_desks = [_raw_desk("Alice", "2", 100), _raw_desk("David", "8", 300)]
    handler = make_handler(desks=raw_desks)
    manager = SeatObservationManager.initialize(handler)
    seat_ui = FakeSeatUI(desks=raw_desks)
    manager._seat_ui = seat_ui

    # 可视区只有 seat 1 有人
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="Alice")

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify

        diverged = await manager.on_focus_count(before=1, current_focus_count=2)

    assert diverged is True
    assert seat_ui.collapsed is True  # 展开后必须收起，恢复聊天视口
    assert manager.seats[7].occupied is True
    assert manager.seats[7].username == "David"
    assert "David" in notify.call_args.kwargs["changed_users"]


@pytest.mark.asyncio
async def test_expansion_inspection_clicks_raw_web_element():
    """展开重扫拿到 raw WebElement 时直接点元素，不走坐标兜底。"""
    elements = soul_elements()
    state_node = ClickableNode()
    raw_desk = RawSeatDesk(
        {
            elements["left_state"]: state_node,
            elements["left_label"]: SimpleNamespace(text="管理"),
            elements["right_label"]: SimpleNamespace(text="2"),
        },
        location={"x": 40, "y": 100},
    )
    handler = make_handler(desks=[raw_desk], popup_name="Bob")
    manager = SeatObservationManager.initialize(handler)
    manager._seat_ui = FakeSeatUI(desks=[raw_desk])

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.expand_rescan_and_collapse(1)

    assert state_node.clicked is True
    assert manager.seats[1].username == "Bob"
    handler.gesture_handler.click_at.assert_not_called()


@pytest.mark.asyncio
async def test_expansion_without_six_desks_keeps_snapshot():
    """expand_and_find_desks 半截返回（None）时不得写入残缺快照，但仍要收起。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    seat_ui = FakeSeatUI(desks=None)
    manager._seat_ui = seat_ui
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="Alice")

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.expand_rescan_and_collapse(2)

    assert changed is False
    assert seat_ui.collapsed is True
    assert manager.seats[1].username == "Alice"  # 快照未被推平
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_inspection_holds_the_real_app_controller_ui_lock():
    """契约：观测层用的是 AppController 真实的 ui_session，不是自造锁 API。"""
    import asyncio

    from ushareiplay.core.app_controller import AppController

    controller = AppController.__new__(AppController)
    controller.ui_lock = asyncio.Lock()
    controller.logger = None  # ui_session 只在有 logger 时打日志

    handler = make_handler(popup_name="Bob", controller=controller)
    manager = SeatObservationManager.initialize(handler)
    lock_states = []
    handler.element_finder.on_wait = lambda: lock_states.append(controller.ui_lock.locked())

    desk = build_desk_wrapper(handler, left="管理", right="2", left_occupied=True)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.observe_visible_desks([desk])

    assert lock_states == [True]
    assert controller.ui_lock.locked() is False


@pytest.mark.asyncio
async def test_controller_without_ui_session_api_fails_loudly():
    """曾经的 hasattr 守卫会让加锁静默失效；接口不符契约时必须炸出来。"""
    from types import SimpleNamespace as _SimpleNamespace

    handler = make_handler(controller=_SimpleNamespace())
    manager = SeatObservationManager.initialize(handler)

    desk = build_desk_wrapper(handler, left="管理", right="2", left_occupied=True)

    with pytest.raises(AttributeError):
        await manager.observe_visible_desks([desk])


def test_seat_manager_does_not_initialize_seat_observation_singleton():
    """
    SeatObservationManager is a Singleton whose creation is limited to the composition root.
    SeatManager must never call SeatObservationManager.initialize(...), so that the composition root
    can initialize SeatObservationManager without raising SingletonError.
    """
    from ushareiplay.managers.seat_manager import SeatManager
    from ushareiplay.managers.seat_manager.base import SeatManagerBase

    SeatObservationManager.reset_instance()
    SeatManagerBase._instance = None
    SeatManager._instance = None

    handler = make_handler()
    seat_mgr = SeatManager.get_instance(handler)

    # SeatManager must not eagerly initialize the singleton
    assert not SeatObservationManager.is_initialized()
    assert seat_mgr.observation is None
    assert seat_mgr._observation is None

    # Composition root initializes SeatObservationManager
    observation = SeatObservationManager.initialize(handler)
    assert SeatObservationManager.is_initialized()
    assert seat_mgr.observation is observation
    assert seat_mgr._observation is observation


@pytest.mark.asyncio
async def test_observe_visible_desks_does_not_acquire_ui_session_when_no_unknown_occupants():
    """监控轮询在没有未解析昵称时不得抢占 ui_session，避免常规监控输出日志与锁竞争。"""
    controller = FakeController()
    handler = make_handler(controller=controller)
    manager = SeatObservationManager.initialize(handler)

    desk = build_desk_wrapper(handler, left="1", right="2")

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.observe_visible_desks([desk])

    # 无需点头像弹窗解析，不应申请 ui_session
    assert controller.sessions == []


@pytest.mark.asyncio
async def test_ui_session_logs_at_debug_level_only():
    """AppController.ui_session 的锁获取/释放仅允许打在 debug 级别，严禁在 critical/info 刷屏。"""
    import asyncio
    from unittest.mock import MagicMock
    from ushareiplay.core.app_controller import AppController

    controller = AppController.__new__(AppController)
    controller.ui_lock = asyncio.Lock()
    mock_logger = MagicMock()
    controller.logger = mock_logger

    async with controller.ui_session("seat_inspect"):
        pass

    assert mock_logger.debug.call_count == 2
    mock_logger.debug.assert_any_call("[ui_lock] acquired: seat_inspect")
    mock_logger.debug.assert_any_call("[ui_lock] released: seat_inspect")
    mock_logger.critical.assert_not_called()
    mock_logger.info.assert_not_called()


def test_format_3row_layout_includes_focus_count():
    """输出日志时输出专注人数，不输出在座人数。"""
    manager = SeatObservationManager.initialize(make_handler())
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="锦鲤")
    manager.seats[6] = SeatSlot(seat_number=6, occupied=True, username="儿童不易")

    log_str = manager.format_3row_layout(trigger_source="可视区域变更", focus_count=6)
    assert "[FocusSeatObservation] 专注麦位状态变更 (触发源: 可视区域变更, 专注人数: 6):" in log_str
    assert "在座人数" not in log_str

    # 当 focus_count 为 None 时回退未知
    manager._last_focus_count = None
    log_str_unknown = manager.format_3row_layout(trigger_source="可视区域变更", focus_count=None)
    assert "专注人数: 未知" in log_str_unknown
    assert "在座人数" not in log_str_unknown


@pytest.mark.asyncio
async def test_expand_rescan_bidirectional_scans_top_and_bottom_rows():
    """全量重扫必须双向滚动（先到第0排扫顶，再到第2排扫底），保证第1排和第3排均不漏扫。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 构造6张桌位：
    # 第1排 (desk 0): 1号 occupied (张三)
    # 第2排 (desk 2): 5号 occupied (李四)
    # 第3排 (desk 4): 9号 occupied (王五)
    desk0 = build_desk_wrapper(handler, left="张三", right="2", left_occupied=True, y=100)
    desk1 = build_desk_wrapper(handler, left="3", right="4", y=100)
    desk2 = build_desk_wrapper(handler, left="李四", right="6", left_occupied=True, y=300)
    desk3 = build_desk_wrapper(handler, left="7", right="8", y=300)
    desk4 = build_desk_wrapper(handler, left="王五", right="10", left_occupied=True, y=500)
    desk5 = build_desk_wrapper(handler, left="11", right="12", y=500)

    # 模拟视口滚动：
    # 顶部视口只能看到 desk 0, 1, 2, 3（前两排）
    top_desks = [desk0, desk1, desk2, desk3]
    # 底部视口只能看到 desk 2, 3, 4, 5（后两排）
    bottom_desks = [desk2, desk3, desk4, desk5]

    scroll_state = {"row": None}
    def mock_find_elements(key):
        if scroll_state["row"] == 0:
            return top_desks
        elif scroll_state["row"] == 2:
            return bottom_desks
        return [desk0, desk1, desk2, desk3, desk4, desk5]

    handler.element_finder.find_elements = mock_find_elements

    fake_seat_ui = FakeSeatUI(desks=top_desks)
    def tracking_scroll_to_row(desk_index, seat_desks=None, duration=100):
        scroll_state["row"] = desk_index // 2
        fake_seat_ui.scrolled_rows.append(desk_index // 2)

    fake_seat_ui.scroll_to_row = tracking_scroll_to_row
    manager._seat_ui = fake_seat_ui

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        changed = await manager.expand_rescan_and_collapse(3)

    assert changed is True
    # 确认执行了双向滚动：先到 row 0，再到 row 2，最后复位 row 0
    assert fake_seat_ui.scrolled_rows == [0, 2, 0]
    # 确认第 1 排（1号）与第 3 排（9号）全部成功采集，没有漏人
    assert manager.seats[1].occupied is True
    assert manager.seats[1].username == "张三"
    assert manager.seats[5].occupied is True
    assert manager.seats[5].username == "李四"
    assert manager.seats[9].occupied is True
    assert manager.seats[9].username == "王五"
    assert sum(1 for s in manager.seats.values() if s.occupied) == 3


def test_extract_seat_info_marks_occupied_when_label_is_nickname_even_without_state_node():
    """即使 state 节点未抓取到，只要 label 是用户昵称，麦位必须判定为占用。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 构造一个没有 left_state 但 left_label 是昵称的 desk
    elements = soul_elements()
    raw_desk = RawSeatDesk(
        {
            elements["left_label"]: SimpleNamespace(text="锦鲤"),
            elements["right_label"]: SimpleNamespace(text="2"),
        },
        location={"x": 40, "y": 100},
    )

    info = manager._extract_seat_info(raw_desk, "left")
    assert info["occupied"] is True
    assert info["username"] == "锦鲤"


@pytest.mark.asyncio
async def test_observe_visible_desks_validates_focus_count_and_triggers_full_scan():
    """验证：如果输出的座位与专注人数对不上（如在座2人但专注6人），必须触发全量重扫。"""
    controller = FakeController()
    handler = make_handler(controller=controller)
    manager = SeatObservationManager.initialize(handler)
    manager.expand_rescan_and_collapse = AsyncMock(return_value=True)

    desk = build_desk_wrapper(handler, left="张三", right="2", left_occupied=True)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        # 专注人数为 6，但当前仅能观测到 1 人在座，必须触发全量扫描
        await manager.observe_visible_desks([desk], current_focus_count=6)

    manager.expand_rescan_and_collapse.assert_awaited_once_with(6)


@pytest.mark.asyncio
async def test_collapsed_seats_do_not_overwrite_third_row_snapshot():
    """折叠状态下的可视区域观测不得把未展开的第三排麦位（9~12号）误推平为空闲。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 预设全量扫描已探明的第三排麦位
    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Chainer")
    manager.seats[11] = SeatSlot(seat_number=11, occupied=True, username="不约儿童")
    manager.seats[12] = SeatSlot(seat_number=12, occupied=True, username="群主", is_owner=True)

    # 模拟座位已收起（折叠状态）
    seat_ui = FakeSeatUI()
    seat_ui.is_expanded = False
    manager._seat_ui = seat_ui

    # 折叠状态下，传递前两排桌位（包含占位与空位）
    desk0 = build_desk_wrapper(handler, left="1", right="2", y=100)
    desk1 = build_desk_wrapper(handler, left="锦鲤", right="儿童不易", left_occupied=True, right_occupied=True, y=200)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.observe_visible_desks([desk0, desk1], current_focus_count=5)

    # 第三排依然保存在快照中，未被推平
    assert manager.seats[9].occupied is True
    assert manager.seats[9].username == "Chainer"
    assert manager.seats[11].occupied is True
    assert manager.seats[11].username == "不约儿童"
    assert manager.seats[12].occupied is True
    assert manager.seats[12].username == "群主"
    assert sum(1 for s in manager.seats.values() if s.occupied) == 5


@pytest.mark.asyncio
async def test_collapsed_state_with_zero_height_or_hidden_desks_does_not_wipe_third_row():
    """当 Appium XML 中带有折叠/零尺寸的桌位节点时，不得误作为可见空座位处理。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Chainer")
    manager.seats[11] = SeatSlot(seat_number=11, occupied=True, username="不约儿童")
    manager.seats[12] = SeatSlot(seat_number=12, occupied=True, username="群主", is_owner=True)

    seat_ui = FakeSeatUI()
    seat_ui.is_expanded = False
    manager._seat_ui = seat_ui

    # 模拟 6 个桌位节点都在 XML 树中，但后两张桌子 bounds 为 [0,0][0,0]（折叠状态）
    desk0 = build_desk_wrapper(handler, left="1", right="2", y=100)
    desk1 = build_desk_wrapper(handler, left="锦鲤", right="儿童不易", left_occupied=True, right_occupied=True, y=200)
    desk2 = build_desk_wrapper(handler, left="7", right="8", y=300)
    desk3 = build_desk_wrapper(handler, left="3", right="4", y=400)
    desk4_collapsed = build_desk_wrapper(handler, left="", right="", y=0)
    desk4_collapsed._xml_element.set("bounds", "[0,0][0,0]")
    desk5_collapsed = build_desk_wrapper(handler, left="", right="", y=0)
    desk5_collapsed._xml_element.set("bounds", "[0,0][0,0]")

    desks = [desk0, desk1, desk2, desk3, desk4_collapsed, desk5_collapsed]

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.observe_visible_desks(desks, current_focus_count=5)

    assert manager.seats[9].occupied is True
    assert manager.seats[9].username == "Chainer"
    assert manager.seats[11].occupied is True
    assert manager.seats[12].occupied is True


def test_is_seat_empty_vs_invisible():
    """验证空座（下座）与看不见（不可见/稀疏内容）的严格区分。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 1. 空座：具备明确的默认名称“点击入座”
    desk_empty_by_default = build_desk_wrapper(handler, left_default_name="点击入座", y=200)
    assert manager._is_seat_empty(desk_empty_by_default, "left") is True

    # 2. 空座：label 为座位编号数字（房间内空位显示编号）
    desk_empty_by_number = build_desk_wrapper(handler, left="5", y=200)
    assert manager._is_seat_empty(desk_empty_by_number, "left") is True

    # 3. 看不见状态：无 state、无 label、无 default_name（例如滑动出视口或仅留底部装饰）
    desk_invisible = build_desk_wrapper(handler, left="", y=200)
    assert manager._is_seat_empty(desk_invisible, "left") is False
    assert manager._is_seat_occupied(desk_invisible, "left") is False

    # 4. 占座状态：state 存在，绝对不是空座
    desk_occupied = build_desk_wrapper(handler, left="锦鲤", left_occupied=True, y=200)
    assert manager._is_seat_occupied(desk_occupied, "left") is True
    assert manager._is_seat_empty(desk_occupied, "left") is False


def test_desk_visibility_requires_minimum_bounds_and_content():
    """验证只有尺寸正常（>=60px）且具有实质麦位内容的桌位才被判定为可视桌位。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 1. 边缘裁切残片（例如高度仅 18px 或 11px），即便在 XML 中也判定为不可见
    desk_clipped = build_desk_wrapper(handler, bounds="[28,566][337,584]")
    assert manager._is_desk_visible(desk_clipped) is False

    # 2. 正常尺寸但内部无任何实质麦位内容（无占座、无编号、无点击入座）
    desk_no_content = build_desk_wrapper(handler, bounds="[28,200][337,400]")
    assert manager._is_desk_visible(desk_no_content) is False

    # 3. 正常尺寸且有占座内容
    desk_with_seat = build_desk_wrapper(handler, left="锦鲤", left_occupied=True, bounds="[28,200][337,400]")
    assert manager._is_desk_visible(desk_with_seat) is True

    # 4. 正常尺寸且有空座内容（点击入座）
    desk_with_empty = build_desk_wrapper(handler, left_default_name="点击入座", bounds="[28,200][337,400]")
    assert manager._is_desk_visible(desk_with_empty) is True


def test_apply_snapshot_preserves_occupant_when_seat_is_invisible():
    """不可见不等于下座：稀疏内容不可见时，必须保留原有占座人，防止被错误清空触发死循环。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 5 号麦位此前已知被“锦鲤”占用
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="锦鲤")

    # 模拟新一轮观测：5 号麦位因不可见导致 occupied=False，且 is_empty=False
    observed = {
        5: (None, "left", {
            "occupied": False,
            "is_empty": False,
            "label": "",
            "username": None,
        })
    }

    manager._apply_snapshot(observed)

    # 必须保留原有占座信息！
    assert manager.seats[5].occupied is True
    assert manager.seats[5].username == "锦鲤"


def test_apply_snapshot_clears_only_when_desk_is_fully_visible_and_clearable():
    """判「下座」的两个前提：桌位完整可见，且该号位被允许清空。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    def _empty_read(**overrides):
        info = {
            "occupied": False,
            "is_empty": True,
            "label": "7",
            "username": None,
            "unclipped": True,
        }
        info.update(overrides)
        return {3: (None, "left", info)}

    # 权威路径（clearable=None，全量重扫读过全部麦位）：桌位完整可见即可判下座
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="Chainer")
    manager._apply_snapshot(_empty_read())
    assert manager.seats[3].occupied is False
    assert manager.seats[3].username is None

    # 被动观测：只有显式列入 clearable 的号位（视口内配对换座的旧位）才允许清空
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="Chainer")
    manager._apply_snapshot(_empty_read(), clearable={5})
    assert manager.seats[3].occupied is True
    assert manager.seats[3].username == "Chainer"

    # 桌位被裁切（几十 px 的残片）时，即便允许清空也不清
    manager._apply_snapshot(_empty_read(unclipped=False), clearable={3})
    assert manager.seats[3].occupied is True


@pytest.mark.asyncio
async def test_real_clipped_desks_do_not_wipe_out_of_view_seats_or_trigger_loop():
    """复现并验证生产真实场景：
    RecyclerView 边缘带有 clipped 桌位残片（h=18, h=11），当前视口仅可见第二排（5~8号）；
    被动监控绝不能将第一排（1~4号）或第三排（9~12号）误清空，人数保持一致，不触发全量重扫。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 初始快照：全量扫描已识别 5 位用户
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="Outlier")
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="锦鲤")
    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Chainer")
    manager.seats[11] = SeatSlot(seat_number=11, occupied=True, username="不约儿童")
    manager.seats[12] = SeatSlot(seat_number=12, occupied=True, username="群主", is_owner=True)
    manager._last_focus_count = 5

    seat_ui = FakeSeatUI()
    seat_ui.is_expanded = False
    manager._seat_ui = seat_ui

    # 模拟生产 page source 中的 6 个 userRoot
    # Desk 0, 1: 顶部裁切边缘 (height=18)
    desk0 = build_desk_wrapper(handler, bounds="[28,566][337,584]")
    desk1 = build_desk_wrapper(handler, bounds="[383,566][692,584]")
    # Desk 2: 第二排左侧（seats 5 & 6）
    desk2 = build_desk_wrapper(handler, left="5", right="6", left_occupied=True, right_occupied=False, bounds="[28,611][337,818]")
    # Desk 3: 第二排右侧（seat 7 empty, seat 8 empty）
    desk3 = build_desk_wrapper(handler, left_default_name="点击入座", right="8", bounds="[383,611][692,818]")
    # Desk 4, 5: 底部裁切边缘 (height=11)
    desk4 = build_desk_wrapper(handler, bounds="[28,845][337,856]")
    desk5 = build_desk_wrapper(handler, bounds="[383,845][692,856]")

    desks = [desk0, desk1, desk2, desk3, desk4, desk5]

    with patch.object(manager, "expand_rescan_and_collapse", new_callable=AsyncMock) as mock_rescan:
        await manager.observe_visible_desks(desks, current_focus_count=5)

        # 验证第一排和第三排所有已在座用户完好保留，未被推平成空闲
        assert manager.seats[1].occupied is True
        assert manager.seats[1].username == "Outlier"
        assert manager.seats[5].occupied is True
        assert manager.seats[5].username == "锦鲤"
        assert manager.seats[9].occupied is True
        assert manager.seats[9].username == "Chainer"
        assert manager.seats[11].occupied is True
        assert manager.seats[11].username == "不约儿童"
        assert manager.seats[12].occupied is True
        assert manager.seats[12].username == "群主"

        # 专注人数 5 与在座人数 5 一致，绝对不应触发全量重扫死循环
        mock_rescan.assert_not_called()


@pytest.mark.asyncio
async def test_passive_observation_never_clears_a_seat_it_cannot_identify():
    """复现 2026-09-26 18:13 那次死循环。

    折叠视口只露出第二排的两张桌位，且两张都读不到麦位编号（空座显示「点击入座」、
    占座侧读不到 state）。旧实现按坐标兜底把它们排成 1/2 号位，第二排空座的读数
    于是把已确认的 3 号位占座（Chainer）推平成空闲 → 在座数 3 ≠ 专注人数 4 →
    再展开重扫 → 恢复 → 再推平，17 秒一轮无限循环。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 全量重扫刚确认的快照：1/3/5/8 号位有人，专注人数 4
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="Outlier")
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="Chainer")
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="锦鲤")
    manager.seats[8] = SeatSlot(seat_number=8, occupied=True, username="群主", is_owner=True)
    manager._last_focus_count = 4

    seat_ui = FakeSeatUI()
    seat_ui.is_expanded = False
    manager._seat_ui = seat_ui

    # 折叠视口：两张第二排桌位，都读不到座位号
    desk_row2_left = build_desk_wrapper(
        handler,
        left_default_name="点击入座",
        right_default_name="点击入座",
        bounds="[40,611][400,771]",
    )
    desk_row2_right = build_desk_wrapper(
        handler,
        left_default_name="点击入座",
        right_default_name="点击入座",
        bounds="[383,611][743,771]",
    )

    with patch.object(manager, "expand_rescan_and_collapse", new_callable=AsyncMock) as mock_rescan:
        changed = await manager.observe_visible_desks(
            [desk_row2_left, desk_row2_right], current_focus_count=4
        )

    # 身份未知的读数一律不写：既不推平 3 号位，也不触发重扫
    assert changed is False
    assert manager.seats[3].occupied is True
    assert manager.seats[3].username == "Chainer"
    assert sum(1 for s in manager.seats.values() if s.occupied) == 4
    mock_rescan.assert_not_called()


@pytest.mark.asyncio
async def test_seat_read_as_empty_without_a_destination_escalates_to_full_rescan():
    """快照里有人、本轮视口读成空，但同轮找不到他的新座位 → 去向不明。

    这种情况既不许推平快照（可能只是走出了可视范围），也不许当作没发生（那会漏检）：
    必须全量扫描一遍取最新信息。同一份读数只扫一次，否则就是每轮十几秒的死循环。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value=None)

    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="锦鲤")
    manager.seats[7] = SeatSlot(seat_number=7, occupied=True, username="不约儿童")

    # 折叠视口只露出第二排两张桌位：空位显示麦位编号（位置可定），快照里那两位却有人
    desks = [
        build_desk_wrapper(
            handler, left="5", right="6", bounds="[40,611][400,771]"
        ),
        build_desk_wrapper(
            handler, left="7", right="8", bounds="[383,611][743,771]"
        ),
    ]

    async def _landed_scan(*_args, **_kwargs):
        manager._last_rescan_ok = True
        return True

    with patch.object(
        manager, "expand_rescan_and_collapse", new_callable=AsyncMock, side_effect=_landed_scan
    ) as mock_rescan:
        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            changed = await manager.observe_visible_desks(desks)

    assert changed is False
    # 快照不被局部读数推平，等全量扫描给结论
    assert manager.seats[5].occupied is True
    assert manager.seats[5].username == "锦鲤"
    assert manager.seats[7].occupied is True
    assert manager.seats[7].username == "不约儿童"
    mock_rescan.assert_awaited_once()
    # 检测到的变更以「号位 + 去向不明」的指纹记录下来
    assert manager._scanned_seat_change_fingerprint == frozenset(
        {(5, "disappear"), (7, "disappear")}
    )

    # 同一份读数再来一轮：已经扫过了，不再重复展开（把冷却清掉，确保拦住它的是指纹）
    manager._last_rescan_time = -1e9
    with patch.object(
        manager, "expand_rescan_and_collapse", new_callable=AsyncMock, side_effect=_landed_scan
    ) as repeat_rescan:
        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            await manager.observe_visible_desks(desks)

    repeat_rescan.assert_not_awaited()


@pytest.mark.asyncio
async def test_appearing_user_still_recorded_elsewhere_escalates_to_full_rescan():
    """可视范围内出现一个人，而快照里他还挂在别的位子上 → 可能是从看不见的位子挪过来的。

    这时既不能直接把新位置写进快照（旧位置会留成幽灵），也不能当作没发生：
    全量扫描一遍。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value=None)

    # 锦鲤此前记录在第三排 9 号位（当前不可视）
    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="锦鲤")

    desk = build_desk_wrapper(handler, left="锦鲤", right="6", left_occupied=True)

    async def _landed_scan(*_args, **_kwargs):
        manager._last_rescan_ok = True
        return True

    with patch.object(
        manager, "expand_rescan_and_collapse", new_callable=AsyncMock, side_effect=_landed_scan
    ) as mock_rescan:
        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            changed = await manager.observe_visible_desks([desk])

    assert changed is False
    assert manager.seats[5].occupied is False   # 新位置不写，等扫描定夺
    assert manager.seats[9].occupied is True    # 旧位置保持，不产生幽灵/也别急着清
    mock_rescan.assert_awaited_once()
    assert ("appear") in {kind for _seat, kind in manager._scanned_seat_change_fingerprint}


@pytest.mark.asyncio
async def test_one_full_rescan_serves_both_signals_in_the_same_observation():
    """同一次观测里人数背离和「去向不明」同时出现 → 只展开扫一次，不排队扫两遍。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value=None)
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="锦鲤")

    desk = build_desk_wrapper(handler, left="5", right="6")

    async def _landed_scan(*_args, **_kwargs):
        manager._last_rescan_ok = True
        return True

    with patch.object(
        manager, "expand_rescan_and_collapse", new_callable=AsyncMock, side_effect=_landed_scan
    ) as mock_rescan:
        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            # 专注 3 人在座 1 人 → 人数背离；同一轮里 5 号位读成空 → 去向不明
            await manager.observe_visible_desks([desk], current_focus_count=3)

    mock_rescan.assert_awaited_once()


@pytest.mark.asyncio
async def test_same_focus_count_is_reconciled_only_once():
    """闸门：专注人数这个取值只允许触发一次全量重扫，人数没变绝不重复展开。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    async def _landed_scan(*_args, **_kwargs):
        manager._last_rescan_ok = True
        return True

    with patch.object(
        manager, "expand_rescan_and_collapse", new_callable=AsyncMock, side_effect=_landed_scan
    ) as mock_rescan:
        # 第一次对账：专注 4 人、在座 0 人 → 展开扫一次
        await manager.on_focus_count(None, 4)
        mock_rescan.assert_awaited_once_with(4)

        # 同一个人数反复上报（事件轮询每轮都会报）不再展开 —— 即便冷却时间早就过了，
        # 只看人数有没有变（旧实现里冷却一过就会再展开一次，这正是死循环的节奏）
        manager._last_rescan_time = 0.0
        await manager.on_focus_count(4, 4)
        manager._last_rescan_time = 0.0
        await manager.observe_visible_desks(
            [build_desk_wrapper(handler, left="1", right="2")], current_focus_count=4
        )
        assert mock_rescan.await_count == 1

        # 人数真的变了才允许再对一次账
        manager._last_rescan_time = 0.0
        await manager.on_focus_count(4, 5)
        assert mock_rescan.await_count == 2
        mock_rescan.assert_awaited_with(5)


@pytest.mark.asyncio
async def test_rescan_that_never_landed_is_retried():
    """扫描没落地（展开失败/半截快照）时闸门要撤掉，不能把信号吞掉。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    # 替身不设置 _last_rescan_ok，模拟「扫了但没扫成」
    manager.expand_rescan_and_collapse = AsyncMock(return_value=False)

    await manager.on_focus_count(None, 4)
    manager.expand_rescan_and_collapse.assert_awaited_once_with(4)

    # 退避期内不重复展开
    manager._last_rescan_time = time.monotonic()
    await manager.on_focus_count(4, 4)
    assert manager.expand_rescan_and_collapse.await_count == 1

    # 退避时间过去后重试（闸门没被永久占用）
    manager._last_rescan_time = -1e9
    await manager.on_focus_count(4, 4)
    assert manager.expand_rescan_and_collapse.await_count == 2





