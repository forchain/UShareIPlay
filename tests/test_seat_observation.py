"""座位被动观测的测试。

替身定义在 tests/seat_fixtures.py —— 刻意与生产协作者同形（见 PR #339 review 的
C1/C2）：desk 是真 ElementWrapper，raw WebElement 路径走 find_element 契约，
controller 用真实的 ui_session 异步上下文管理器。
"""

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

    assert "[FocusSeatObservation] 专注麦位状态变更 (触发源: 测试触发, 专注人数: 未知, 在座人数: 4):" in lines[0]
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


def test_map_desks_to_indices_fallback_by_coordinates():
    # 昵称占满可视桌位，读不到座位号，只能靠坐标聚类
    manager = SeatObservationManager.initialize(make_handler())
    desks = [
        build_desk_wrapper(manager.handler, left="群主", right="A", y=500),
        build_desk_wrapper(manager.handler, left="B", right="C", y=100),
        build_desk_wrapper(manager.handler, left="D", right="E", y=300),
        build_desk_wrapper(manager.handler, left="F", right="G", y=200),
    ]

    mapped = manager.map_desks_to_indices(desks)

    assert [idx for idx, _ in mapped] == [0, 1, 2, 3]


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
async def test_occupant_swap_is_detected():
    """R2 回归：座位上换人不能被旧昵称覆盖掉。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value=None)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="张三", label="张三")

    desk = build_desk_wrapper(handler, left="李四", right="2", left_occupied=True)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.observe_visible_desks([desk])

    assert changed is True
    assert manager.seats[1].username == "李四"
    kwargs = notify.call_args.kwargs
    assert set(kwargs["changed_users"]) == {"张三", "李四"}
    assert kwargs["seat_info"]["张三"] == {"seat_number": 1, "action": "leave_seat"}
    assert kwargs["seat_info"]["李四"] == {"seat_number": 1, "action": "sit_down"}


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


def test_format_3row_layout_includes_focus_count_and_seated_count():
    """输出日志时必须同时输出专注人数和在座人数。"""
    manager = SeatObservationManager.initialize(make_handler())
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="锦鲤")
    manager.seats[6] = SeatSlot(seat_number=6, occupied=True, username="儿童不易")

    log_str = manager.format_3row_layout(trigger_source="可视区域变更", focus_count=6)
    assert "[FocusSeatObservation] 专注麦位状态变更 (触发源: 可视区域变更, 专注人数: 6, 在座人数: 2):" in log_str

    # 当 focus_count 为 None 时回退未知
    manager._last_focus_count = None
    log_str_unknown = manager.format_3row_layout(trigger_source="可视区域变更", focus_count=None)
    assert "专注人数: 未知, 在座人数: 2" in log_str_unknown


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




