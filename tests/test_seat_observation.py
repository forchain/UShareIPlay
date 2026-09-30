"""座位被动观测的测试。

替身定义在 tests/seat_fixtures.py —— 刻意与生产协作者同形（见 PR #339 review 的
C1/C2）：desk 是真 ElementWrapper，raw WebElement 路径走 find_element 契约，
controller 用真实的 ui_session 异步上下文管理器。
"""

import asyncio
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.seat_fixtures import (
    SEAT_DOM_FIXTURES,
    ClickableNode,
    FakeController,
    FakeSeatUI,
    RawSeatDesk,
    build_base_fragment_wrapper,
    build_desk_wrapper,
    build_live_desk_wrapper,
    build_live_raw_desk,
    build_real_desk_wrappers,
    build_real_raw_desks,
    load_real_desk_nodes,
    make_handler,
    soul_elements,
)
from lxml import etree

from ushareiplay.core.element_wrapper import ElementWrapper
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationGateState,
    SeatObservationManager,
    SeatRescanCooldownPolicy,
    SeatSlot,
)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float):
        self.current += seconds


@pytest.fixture(autouse=True)
def reset_observation():
    SeatObservationManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()


def test_format_3row_layout_visual_representation():
    from ushareiplay.core.log_formatter import strip_ansi

    manager = SeatObservationManager.initialize(None)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="群主", is_owner=True)
    manager.seats[2] = SeatSlot(seat_number=2, occupied=False)
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="张三")
    manager.seats[7] = SeatSlot(seat_number=7, occupied=True, username="李四")
    manager.seats[11] = SeatSlot(seat_number=11, occupied=True, username="王五")

    layout = manager.format_3row_layout("测试触发")
    # 着色不许改一个字的内容：文本比对一律按剥掉转义码之后的样子
    lines = strip_ansi(layout).splitlines()

    assert "[FocusSeatObservation] 专注麦位状态变更 (触发源: 测试触发, 专注人数: 未知):" in lines[0]
    assert "第一排: [1号: 群主] [2号: 空闲]  |  [3号: 张三] [4号: 空闲]" in lines[1]
    assert "第二排: [5号: 空闲] [6号: 空闲]  |  [7号: 李四] [8号: 空闲]" in lines[2]
    assert "第三排: [9号: 空闲] [10号: 空闲]  |  [11号: 王五] [12号: 空闲]" in lines[3]

    # 在座亮青、空闲压暗，两种颜色都在
    assert f"{manager.SEAT_COLOR_OCCUPIED}[3号: 张三]{manager.SEAT_COLOR_RESET}" in layout
    assert f"{manager.SEAT_COLOR_IDLE}[2号: 空闲]{manager.SEAT_COLOR_RESET}" in layout


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
async def test_inspect_occupant_never_presses_back_when_no_popup_opened():
    """点名没打开弹窗时绝不能按 back：房间界面上的一次 back 就是退出派对。

    真机 09-28 20:46:43：房主换座后 9 号位的残留渲染被读成「占座但身份未知」，
    被动观测按设计点头像读昵称；此时面板已收起，按快照坐标点出去没有打开任何
    弹窗（1.5s 超时正是「弹窗没开」的正面证据），finally 却兜底按了一次 back ——
    房间界面就此消失，紧接着的全量重扫连座位按钮都找不到（未找到座位按钮，
    无法展开座位）。超时读数本身就是判据：没读到昵称节点＝没有可关的弹窗。
    """
    handler = make_handler(popup_name=None)
    manager = SeatObservationManager.initialize(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    username = await manager.inspect_occupant(desk, "left", 9)

    assert username is None
    handler.key_actions.press_back.assert_not_called()


@pytest.mark.asyncio
async def test_inspect_occupant_closes_the_popup_it_actually_opened():
    """弹窗真开了（读到昵称节点）就必须关掉：麦位读数还在后面，卡片不许留在屏幕上。"""
    handler = make_handler(popup_name="Bob")
    manager = SeatObservationManager.initialize(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    username = await manager.inspect_occupant(desk, "left", 9)

    assert username == "Bob"
    handler.key_actions.press_back.assert_called_once()


@pytest.mark.asyncio
async def test_inspect_occupant_does_not_press_back_when_the_tap_never_landed():
    """连点都没点出去（坐标缺失/手势失败）时按 back 同样是盲按。"""
    handler = make_handler(popup_name="Bob")
    handler.gesture_handler.click_at.return_value = False
    manager = SeatObservationManager.initialize(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    username = await manager.inspect_occupant(desk, "left", 9)

    assert username is None
    handler.key_actions.press_back.assert_not_called()


@pytest.mark.asyncio
async def test_inspect_occupant_still_closes_a_card_that_rendered_after_the_timeout():
    """昵称没读出来但卡片已经在屏幕上：仍要关掉，否则它会挡住后面的麦位读数。"""
    handler = make_handler(popup_name=None)
    handler.element_finder.popup_open = True  # 卡片在屏幕上，只是昵称节点读不出文字
    manager = SeatObservationManager.initialize(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    username = await manager.inspect_occupant(desk, "left", 9)

    assert username is None
    handler.key_actions.press_back.assert_called_once()


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

    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()

    handler = make_handler()
    seat_mgr = SeatManager.initialize(handler)

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


def test_no_pixel_height_threshold_constant_remains():
    """#341：FULL_DESK_MIN_HEIGHT 连同所有 bounds 宽高阈值必须彻底删除。"""
    assert not hasattr(SeatObservationManager, "FULL_DESK_MIN_HEIGHT")


def test_seat_dom_is_read_regardless_of_pixel_size():
    """几十像素的残片只要 DOM 里有麦位就必须照读 —— 高度不再是可见性的代理。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 40x18px（旧实现里宽高都 <60 会被整张丢弃）
    clipped = build_desk_wrapper(handler, left="1", right="2", bounds="[10,566][50,584]")

    assert manager._is_desk_visible(clipped) is True
    assert manager.map_desks_to_indices([clipped]) == [(0, clipped)]
    info = manager._extract_seat_info(clipped, "left", 1)
    assert info["occupied"] is False
    assert info["is_empty"] is True


def test_empty_seat_with_single_avatar_image_is_empty():
    """空座只剩 AvatarView 里的一张占位图（没有编号、没有「点击入座」）也要判为空座。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 右侧 "2" 把桌位钉在 desk 0；左侧空座没有任何文字，只有一张占位图
    desk = build_desk_wrapper(handler, right="2", left_avatar_images=1)

    info = manager._extract_seat_info(desk, "left", 1)
    assert info["occupied"] is False
    assert info["is_empty"] is True
    assert info["avatar_images"] == 1


def test_occupied_seat_with_multiple_avatar_images_is_occupied():
    """占座麦位的 AvatarView 有多张图（头像 + 挂件/边框），即便读不到昵称也算占座。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    desk = build_desk_wrapper(handler, right="2", left_avatar_images=3)

    info = manager._extract_seat_info(desk, "left", 1)
    assert info["occupied"] is True
    assert info["is_empty"] is False
    assert info["avatar_images"] == 3


def test_occupied_seat_with_state_widgets_is_occupied():
    """ClState 里的活跃控件（勋章、专注时长）本身就是占座证据，不依赖头像或昵称。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    desk = build_desk_wrapper(handler, right="2", left_state_widgets=True)

    info = manager._extract_seat_info(desk, "left", 1)
    assert info["occupied"] is True
    assert info["is_empty"] is False
    assert info["has_state"] is True
    assert info["username"] is None  # 昵称留给权威路径点头像弹窗补齐


def test_bare_clstate_reads_as_occupied():
    """ClState 存在即占座：空座渲染 TvDefaultName 或麦位编号、不带 ClState。

    这与 seating.py 定座流程的判据（bool(left_state)）同源，也是 CONTEXT.md 写的
    「ClState presence」；勋章/专注时长等活跃控件因此天然覆盖（见 #341）。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # leftClState 在，但里面既没有勋章/时长，也没有昵称
    desk = build_desk_wrapper(handler, left_occupied=True, right="2")

    info = manager._extract_seat_info(desk, "left", 1)
    assert info["has_state"] is True
    assert info["avatar_images"] == 0
    assert info["occupied"] is True
    assert info["is_empty"] is False


def test_raw_desk_avatar_image_count_is_unreadable_and_never_clears_a_seat():
    """展开重扫的 raw WebElement 数不到 AvatarView 的图片（Appium 的 XPath 是整页
    作用域，数下去会数到全屏的图），所以这类读数只能靠 ClState / 昵称 / 编号。

    数不到时必须落在「未知」上：既不算占座也不算空座，绝不能凭一个半截读数把人推平。
    """
    elements = soul_elements()
    raw_desk = RawSeatDesk(
        {
            elements["left_avatar"]: SimpleNamespace(),  # 有 AvatarView 节点，但没有图片可数
            elements["right_label"]: SimpleNamespace(text="2"),
        },
        location={"x": 40, "y": 100},
    )
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    info = manager._extract_seat_info(raw_desk, "left", 1)
    assert info["avatar_images"] == 0
    assert info["occupied"] is False
    assert info["is_empty"] is False


def test_avatar_view_without_images_is_unknown_not_empty():
    """占位图都没渲染出来时既不算占座也不算空座：宁可不写，不可猜。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    desk = build_desk_wrapper(handler, right="2")

    info = manager._extract_seat_info(desk, "left", 1)
    assert info["occupied"] is False
    assert info["is_empty"] is False
    assert manager._is_desk_visible(desk) is True  # 右侧有编号，桌位本身仍可用


def test_base_only_fragment_produces_no_seat_slot_data():
    """只渲染底座的残片（bgRoot + left/rightBottomView）不产出任何麦位数据。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    fragment = build_base_fragment_wrapper(handler, y=566)

    assert manager._has_desk_content(fragment) is False
    assert manager._is_desk_visible(fragment) is False
    assert manager.map_desks_to_indices([fragment]) == []


@pytest.mark.asyncio
async def test_observation_of_base_only_fragment_writes_nothing():
    """底座残片既不能推平快照，也不构成变更 —— 它不是任何一个麦位的读数。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="张三")
    manager._last_focus_count = 1

    with patch.object(manager, "expand_rescan_and_collapse", new_callable=AsyncMock) as mock_rescan:
        changed = await manager.observe_visible_desks(
            [build_base_fragment_wrapper(handler, y=566)], current_focus_count=1
        )

    assert changed is False
    assert manager.seats[1].occupied is True
    assert manager.seats[1].username == "张三"
    mock_rescan.assert_not_called()


@pytest.mark.asyncio
async def test_full_rescan_clears_seat_showing_only_the_placeholder_image():
    """权威路径的落快照逻辑：空座只有一张占位图（读不到编号）也要判下座并发离座事件。

    这里 desk 用快照形状（与被动观测同一套读数）；生产上展开重扫拿到的是 raw
    WebElement，数不到占位图，见 test_raw_desk_avatar_image_count_is_unreadable_and_never_clears_a_seat。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="张三")

    desk = build_desk_wrapper(handler, right="2", left_avatar_images=1)
    manager._seat_ui = FakeSeatUI(desks=[desk])

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.expand_rescan_and_collapse(0)

    assert changed is True
    assert manager.seats[1].occupied is False
    assert manager.seats[1].username is None
    assert notify.call_args.kwargs["seat_info"]["张三"] == {
        "seat_number": 1,
        "action": "leave_seat",
    }


@pytest.mark.asyncio
async def test_full_rescan_inspects_occupant_of_seat_with_multiple_avatar_images():
    """权威路径：AvatarView 多图判定占座后点头像弹窗取真实昵称，再发上座事件。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.inspect_occupant = AsyncMock(return_value="Bob")

    desk = build_desk_wrapper(handler, right="2", left_avatar_images=3)
    manager._seat_ui = FakeSeatUI(desks=[desk])

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.expand_rescan_and_collapse(1)

    assert changed is True
    assert manager.seats[1].occupied is True
    assert manager.seats[1].username == "Bob"
    assert notify.call_args.kwargs["seat_info"]["Bob"] == {
        "seat_number": 1,
        "action": "sit_down",
    }


def test_seat_reads_as_empty_vs_invisible():
    """验证空座（下座）与看不见（不可见/稀疏内容）的严格区分。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    def _read(**kwargs) -> dict:
        return manager._extract_seat_info(build_desk_wrapper(handler, y=200, **kwargs), "left", 1)

    # 1. 空座：具备明确的默认名称“点击入座”
    empty_by_default = _read(left_default_name="点击入座")
    assert empty_by_default["is_empty"] is True
    assert empty_by_default["occupied"] is False

    # 2. 空座：label 为座位编号数字（房间内空位显示编号）
    empty_by_number = _read(left="1")
    assert empty_by_number["is_empty"] is True
    assert empty_by_number["occupied"] is False

    # 3. 看不见状态：无 state、无 label、无 default_name、无占位图
    #    （例如滑动出视口或仅留底部装饰）—— 既不是空座，也不是占座
    invisible = _read(left="")
    assert invisible["is_empty"] is False
    assert invisible["occupied"] is False

    # 4. 占座状态：state 存在，绝对不是空座
    occupied = _read(left="锦鲤", left_occupied=True)
    assert occupied["occupied"] is True
    assert occupied["is_empty"] is False


def test_desk_visibility_requires_dom_content_not_bounds():
    """桌位是否可用只看 DOM 证据，像素宽高一律不参与判定（见 #341）。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 1. 边缘裁切残片（高 18px）：DOM 里没有麦位证据 → 不可用
    desk_clipped = build_desk_wrapper(handler, bounds="[28,566][337,584]")
    assert manager._is_desk_visible(desk_clipped) is False

    # 2. 正常尺寸但内部无任何麦位 DOM（无占座、无编号、无点击入座、无占位图）
    desk_no_content = build_desk_wrapper(handler, bounds="[28,200][337,400]")
    assert manager._is_desk_visible(desk_no_content) is False

    # 3. 有占座内容
    desk_with_seat = build_desk_wrapper(handler, left="锦鲤", left_occupied=True, bounds="[28,200][337,400]")
    assert manager._is_desk_visible(desk_with_seat) is True

    # 4. 有空座内容（点击入座）
    desk_with_empty = build_desk_wrapper(handler, left_default_name="点击入座", bounds="[28,200][337,400]")
    assert manager._is_desk_visible(desk_with_empty) is True

    # 5. 高 18px 的残片只要 DOM 里有麦位（这里是空座占位图）就照读
    desk_clipped_with_seat = build_desk_wrapper(
        handler, right="2", left_avatar_images=1, bounds="[28,566][337,584]"
    )
    assert manager._is_desk_visible(desk_clipped_with_seat) is True

    # 6. 只渲染底座的残片（没有 userView）永远不产出麦位数据
    assert manager._is_desk_visible(build_base_fragment_wrapper(handler)) is False


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


def test_apply_snapshot_clears_only_on_explicit_empty_evidence_and_clearable():
    """判「下座」的两个前提：DOM 读出明确空座，且该号位被允许清空。

    像素高度不再是判据 —— 「读不到空座证据」（滑出视口/折叠/底座残片）由
    _judge_empty 直接挡在 is_empty 之外（见 test_apply_snapshot_preserves_occupant_when_seat_is_invisible
    与 test_base_only_fragment_produces_no_seat_slot_data）。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    def _empty_read():
        return {
            3: (
                None,
                "left",
                {
                    "occupied": False,
                    "is_empty": True,
                    "label": "7",
                    "username": None,
                },
            )
        }

    # 权威路径（clearable=None，全量重扫读过全部麦位）：读到明确空座即可判下座
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="Chainer")
    manager._apply_snapshot(_empty_read())
    assert manager.seats[3].occupied is False
    assert manager.seats[3].username is None

    # 被动观测：只有显式列入 clearable 的号位（视口内配对换座的旧位）才允许清空
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="Chainer")
    manager._apply_snapshot(_empty_read(), clearable={5})
    assert manager.seats[3].occupied is True
    assert manager.seats[3].username == "Chainer"

    # 列入 clearable 的号位读到明确空座就清
    manager._apply_snapshot(_empty_read(), clearable={3})
    assert manager.seats[3].occupied is False


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
    clock = FakeClock()
    policy = SeatRescanCooldownPolicy(time_fn=clock)
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler, cooldown_policy=policy)
    # 替身不设置 _last_rescan_ok，模拟「扫了但没扫成」
    manager.expand_rescan_and_collapse = AsyncMock(return_value=False)

    await manager.on_focus_count(None, 4)
    manager.expand_rescan_and_collapse.assert_awaited_once_with(4)

    # 退避期内不重复展开（生产默认 retry 退避为 30 秒，前进 10 秒仍在退避期）
    clock.advance(10.0)
    await manager.on_focus_count(4, 4)
    assert manager.expand_rescan_and_collapse.await_count == 1

    # 退避时间过去后重试（闸门没被永久占用，再前进 25 秒，总计 35s > 30s）
    clock.advance(25.0)
    await manager.on_focus_count(4, 4)
    assert manager.expand_rescan_and_collapse.await_count == 2


def test_avatar_image_count_matches_real_appium_xml_tag():
    """真实 Appium page_source 的节点是 <android.widget.ImageView>，不带 class 属性。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    xml = """
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/userRoot">
      <android.view.ViewGroup resource-id="cn.soulapp.android:id/leftUserView">
        <android.widget.FrameLayout resource-id="cn.soulapp.android:id/leftAvatarView">
          <android.widget.ImageView/>
          <android.widget.ImageView/>
          <android.widget.ImageView/>
        </android.widget.FrameLayout>
      </android.view.ViewGroup>
    </android.view.ViewGroup>
    """
    desk = ElementWrapper(etree.fromstring(xml.encode()), handler, "seat_desk")
    assert manager._avatar_image_count(desk, "left") == 3


@pytest.mark.asyncio
async def test_move_seat_to_collapsed_row_triggers_full_rescan():
    """用户从折叠不可见的 11 号位换座到折叠可视的 7 号位时，必须触发全量重扫。

    在折叠状态下，第二排桌位的麦位标签（leftTvLabelH / ClState）通常未渲染或被裁剪，
    麦位判定完全依赖 AvatarView 里的 ImageView 数量。
    真实 Appium XML 节点为 <android.widget.ImageView>。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 初始快照（与线上日志一致）：5锦鲤，6儿童不易，11 Outlier，12群主
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="锦鲤")
    manager.seats[6] = SeatSlot(seat_number=6, occupied=True, username="儿童不易")
    manager.seats[11] = SeatSlot(seat_number=11, occupied=True, username="Outlier")
    manager.seats[12] = SeatSlot(seat_number=12, occupied=True, username="群主", is_owner=True)
    manager._reconciled_focus_count = 4
    manager._last_focus_count = 4

    def build_real_desk(desk_idx, left_imgs, right_imgs, left_lbl="", right_lbl=""):
        xml = f"""
        <android.view.ViewGroup resource-id="cn.soulapp.android:id/userRoot" bounds="[40,{desk_idx*100}][400,{desk_idx*100+160}]">
          <android.view.ViewGroup resource-id="cn.soulapp.android:id/leftUserView">
            <android.widget.FrameLayout resource-id="cn.soulapp.android:id/leftAvatarView">
              {''.join('<android.widget.ImageView/>' for _ in range(left_imgs))}
            </android.widget.FrameLayout>
            {f'<android.widget.TextView resource-id="cn.soulapp.android:id/leftTvLabelH" text="{left_lbl}"/>' if left_lbl else ''}
          </android.view.ViewGroup>
          <android.view.ViewGroup resource-id="cn.soulapp.android:id/rightUserView">
            <android.widget.FrameLayout resource-id="cn.soulapp.android:id/rightAvatarView">
              {''.join('<android.widget.ImageView/>' for _ in range(right_imgs))}
            </android.widget.FrameLayout>
            {f'<android.widget.TextView resource-id="cn.soulapp.android:id/rightTvLabelH" text="{right_lbl}"/>' if right_lbl else ''}
          </android.view.ViewGroup>
        </android.view.ViewGroup>
        """
        return ElementWrapper(etree.fromstring(xml.encode()), handler, "seat_desk")

    # 4 张可见桌位（折叠状态视口）
    d0 = build_real_desk(0, 1, 1, "1", "2")
    d1 = build_real_desk(1, 1, 1, "3", "4")
    d2 = build_real_desk(2, 2, 2, "锦鲤", "儿童不易")
    # 7 号位（左侧）Outlier 坐下，3 张 ImageView，折叠未渲染 label；8 号位空闲
    d3 = build_real_desk(3, 3, 1, "", "8")

    desks = [d0, d1, d2, d3]

    with patch.object(manager, "expand_rescan_and_collapse", new_callable=AsyncMock) as mock_rescan:
        mock_rescan.return_value = True
        with patch.object(manager, "inspect_occupant", new_callable=AsyncMock) as mock_inspect:
            mock_inspect.return_value = "Outlier"
            await manager.observe_visible_desks(desks, current_focus_count=4)

    mock_rescan.assert_awaited_once_with(4)








# ---------------------------------------------------------------------------
# 真机视口夹具（tests/fixtures/seat_dom/，从设备实测 page_source dump 裁剪）：
# config.yaml 里 left_label/rightTvLabelH 只在普通用户占座时才是座位号数字，
# 群主/管理占座显示身份文字、空座根本没有 label 节点 —— 所以「群主在第二排、
# 第二排只露出顶部一角」的视口一个数字锚点都拿不到。下面这些用例就覆盖这种
# 真实视口，避免再用构造 DOM 的假设去掩盖生产分歧（#341 的教训）。
# ---------------------------------------------------------------------------


def _real_raw_desks_without_number_anchors(fixture_name: str) -> list:
    """真机相位读数，把数字 label 换成身份文字（等价于可见带位里没有普通用户占座）。"""
    desks = build_real_raw_desks(fixture_name)
    for desk in desks:
        for node in desk.children.values():
            if node.text.strip().isdigit():
                node.text = "管理"
    return desks


def test_real_top_phase_maps_leading_desks_without_anchor():
    """展开重扫顶相位（滚动被内容顶部夹住）：真机几何下没有锚点也能定出座位号。

    夹具是实测的展开态首相位：第 0 排满高、第 1 排满高、第 2 排裁到 45px。
    """
    manager = SeatObservationManager.initialize(make_handler())

    observed = manager._read_visible_seats(
        _real_raw_desks_without_number_anchors("expanded_top_with_anchor.xml"), band="top"
    )

    # 夹具当时的真机事实：1 号位群主、5 号位（第二排左）有人占座，其余空座
    assert sorted(observed) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert observed[1][2]["occupied"] is True
    assert observed[1][2]["is_owner"] is True
    assert observed[5][2]["occupied"] is True
    assert observed[5][2]["username"] is None  # 身份文字不能用当昵称
    assert observed[6][2]["is_empty"] is True


def test_real_bottom_phase_maps_trailing_desks_without_anchor():
    """展开重扫底相位（滚动被内容底部夹住）：真机几何下没有锚点也能定出座位号。

    夹具是实测的滚到底相位：第 0 排只剩上方残片，第 1、2 排满高。
    """
    manager = SeatObservationManager.initialize(make_handler())

    observed = manager._read_visible_seats(
        _real_raw_desks_without_number_anchors("expanded_scrolled_bottom.xml"), band="bottom"
    )

    assert sorted(observed) == [5, 6, 7, 8, 9, 10, 11, 12]
    assert observed[5][2]["occupied"] is True  # 真机：5 号位有人
    assert observed[6][2]["is_empty"] is True
    assert observed[12][2]["is_empty"] is True


def test_phase_mapping_refuses_when_panel_is_at_the_other_end():
    """相位兜底必须过几何校验：面板没滚到那一端时绝不按相位硬排（会写错座位号）。"""

    manager = SeatObservationManager.initialize(make_handler())
    top_leaning = _real_raw_desks_without_number_anchors("expanded_top_with_anchor.xml")
    bottom_leaning = _real_raw_desks_without_number_anchors("expanded_scrolled_bottom.xml")

    assert manager._read_visible_seats(top_leaning, band="bottom") == {}
    assert manager._read_visible_seats(bottom_leaning, band="top") == {}


def test_mid_scroll_viewport_stays_unknown():
    """中间滚动位置（上方和下方都还有桌位）不猜 —— 复现 #341 之前错配座位号的成因。"""

    manager = SeatObservationManager.initialize(make_handler())
    desks = _real_raw_desks_without_number_anchors("collapsed_scrolled_after_collapse.xml")

    for band in (None, "top", "bottom"):
        assert manager._read_visible_seats(desks, band=band) == {}


def test_real_collapsed_viewport_without_anchor_maps_nothing():
    """被动观测的保守语义不变：身份未知（既无锚点也无相位）时整屏读数丢弃。

    这就是本次 bug 的现场：真机折叠视口里群主在 1 号位、第二排只露一角，
    没有任何数字锚点，旧实现整屏丢弃 -> 第二排任何变动都读不到。
    """

    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    wrappers = build_real_desk_wrappers(handler, "collapsed_top_no_anchor.xml")

    assert manager._read_visible_seats(wrappers) == {}


def _collapsed_wrappers_with_second_row_occupant_gone(handler) -> list:
    """真机折叠夹具的最小改动：第二排左侧那角的挂件图删到只剩一张占位图 = 人离座。"""

    nodes = load_real_desk_nodes("collapsed_top_no_anchor.xml")
    for node in nodes:
        desk_bounds = node.get("bounds") or ""
        if desk_bounds.startswith("[28,800"):  # 第二排左桌位（5/6 号位）
            avatars = node.findall(".//*[@resource-id='cn.soulapp.android:id/leftAvatarView']")
            for avatar in avatars:
                for image in list(avatar)[1:]:  # 空座只剩一张占位图
                    avatar.remove(image)
    return [ElementWrapper(node, handler, "seat_desk") for node in nodes]


@pytest.mark.asyncio
async def test_real_collapsed_second_row_change_escalates_without_anchor():
    """真机折叠视口里第二排变动：读数进不了快照，但必须升级为全量重扫。

    重扫的相位由本管理器自己滚出来（顶相位/底相位是已知几何），能把座位号对上，
    座位变更事件才有机会触发 —— 否则「第二排换座没有事件」会一直复现。
    """

    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    before = build_real_desk_wrappers(handler, "collapsed_top_no_anchor.xml")
    await manager.observe_visible_desks(before)  # 记下基线指纹（此轮不应触发重扫）

    after = _collapsed_wrappers_with_second_row_occupant_gone(handler)
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as rescan:
        rescan.return_value = True
        await manager.observe_visible_desks(after)

    assert rescan.await_count == 1
    assert "identity is unknown" in rescan.await_args.kwargs["reason"]


@pytest.mark.asyncio
async def test_real_collapsed_viewport_without_change_does_not_rescan():
    """指纹没变就不重扫：避免身份未知的稳定视口把重扫当监控用（铁律：无行为不刷日志）。"""

    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    first = build_real_desk_wrappers(handler, "collapsed_top_no_anchor.xml")
    second = build_real_desk_wrappers(handler, "collapsed_top_no_anchor.xml")
    await manager.observe_visible_desks(first)

    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as rescan:
        rescan.return_value = True
        await manager.observe_visible_desks(second)

    assert rescan.await_count == 0


@pytest.mark.asyncio
async def test_band_change_signal_survives_failed_rescan():
    """重扫没落地时变更信号不能被消费掉：下一轮还得再试。

    真机复现（23:57:56）：换座后指纹兜底触发了重扫，但展开按钮当时找不到
    （Failed to expand seats for full rescan），快照就停在旧座位上了。
    """

    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    await manager.observe_visible_desks(
        build_real_desk_wrappers(handler, "collapsed_top_no_anchor.xml")
    )
    after = _collapsed_wrappers_with_second_row_occupant_gone(handler)

    async def failed_scan(*_args, **_kwargs):
        manager._last_rescan_ok = False  # 扫描跑了但没落地
        return True

    with patch.object(manager, "_request_full_scan", side_effect=failed_scan) as rescan:
        await manager.observe_visible_desks(after)

    assert rescan.await_count == 1
    assert manager._band_change_reason is not None  # 信号留着，冷却结束后重试


@pytest.mark.asyncio
async def test_rescan_falls_back_to_on_screen_desks_when_expansion_unavailable():
    """展开按钮不可用（弹窗切换/面板已展开）时退回当前桌位继续扫，不整轮放弃。"""

    raw_desks = _real_raw_desks_without_number_anchors("expanded_top_with_anchor.xml")
    handler = make_handler(desks=raw_desks)
    manager = SeatObservationManager.initialize(handler)
    manager._seat_ui = FakeSeatUI(desks=None)  # 展开失败

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.expand_rescan_and_collapse(target_focus_count=2)

    assert manager._last_rescan_ok is True
    assert manager.seats[1].occupied is True  # 真机夹具：1 号位是群主
    assert manager.seats[5].occupied is True  # 真机夹具：5 号位有人


@pytest.mark.asyncio
async def test_sync_current_viewport_extracts_desks_and_updates_snapshot_with_band_top():
    """sync_current_viewport 从 driver.page_source 提取桌位并根据 top 相位更新快照。"""
    handler = make_handler()
    xml_content = (
        Path(__file__).resolve().parent / "fixtures" / "seat_dom" / "expanded_top_with_anchor.xml"
    ).read_text(encoding="utf-8")
    handler.driver = MagicMock()
    handler.driver.page_source = xml_content

    manager = SeatObservationManager.initialize(handler)
    # 预设快照中 2 号位原为占座，检验视口同步能将真实空座清空
    manager.seats[2] = SeatSlot(seat_number=2, occupied=True, username="旧占用者")

    observed = await manager.sync_current_viewport(band="top")

    assert 1 in observed
    assert 2 in observed
    assert 5 in observed

    # 1 号位在真机夹具中为群主占用
    assert manager.seats[1].occupied is True
    assert manager.seats[1].is_owner is True
    assert manager.seats[1].username == "群主"

    # 2 号位在真机夹具中为“点击入座”空座，快照应被正确清空
    assert manager.seats[2].occupied is False
    assert manager.seats[2].username is None

    # 5 号位在真机夹具中为占用
    assert manager.seats[5].occupied is True


@pytest.mark.asyncio
async def test_sync_current_viewport_with_band_bottom_preserves_unseen_seats():
    """sync_current_viewport 在 bottom 相位下只更新可见麦位（5~12），保留顶部麦位原值。"""
    handler = make_handler()
    xml_content = (
        Path(__file__).resolve().parent / "fixtures" / "seat_dom" / "expanded_scrolled_bottom.xml"
    ).read_text(encoding="utf-8")
    handler.driver = MagicMock()
    handler.driver.page_source = xml_content

    manager = SeatObservationManager.initialize(handler)
    # 预先设置 1 号位群主与 9 号位旧占用者
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="群主", is_owner=True)
    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="旧占用者")

    observed = await manager.sync_current_viewport(band="bottom")

    # bottom 视口覆盖 5~12 号位
    assert 9 in observed
    assert 1 not in observed

    # 1 号位不在 bottom 视口中，必须被完好保留
    assert manager.seats[1].occupied is True
    assert manager.seats[1].username == "群主"

    # 9 号位在真机夹具中为空座（点击入座），快照中旧占用者被清空
    assert manager.seats[9].occupied is False
    assert manager.seats[9].username is None


@pytest.mark.asyncio
async def test_mark_owner_seated_updates_snapshot_and_suppresses_focus_count_divergence():
    """就座后立即写入快照、预增基准并标记已对账，下游 +1 专注人数事件不再触发全量展开重扫。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager._last_focus_count = 2

    # 模拟确认就座 2 号位
    manager.mark_owner_seated(2)

    # 验证快照与基准
    assert manager.seats[2].occupied is True
    assert manager.seats[2].is_owner is True
    assert manager.seats[2].username == "群主"
    assert manager._last_focus_count == 3
    assert manager._reconciled_focus_count == 3

    # 下游事件到来：专注人数变为 3（+1）
    with patch.object(manager, "expand_rescan_and_collapse", new_callable=AsyncMock) as mock_rescan:
        triggered = await manager.on_focus_count(before=2, current_focus_count=3)
        assert triggered is False
        mock_rescan.assert_not_called()




def _raw_desk_sides(left: tuple, right: tuple, y: int) -> RawSeatDesk:
    """按侧构造展开重扫路径的 desk：(label, occupied)。

    occupied 且 label 为空 = 「读到占座、但昵称这一轮读不出来」，真机上刚落座、
    昵称节点还没渲染出来时就是这个形状（占用证据是 ClState）。
    """
    elements = soul_elements()
    children = {}
    for side, (label, occupied) in (("left", left), ("right", right)):
        children[elements[f"{side}_label"]] = SimpleNamespace(text=label)
        if occupied:
            children[elements[f"{side}_state"]] = SimpleNamespace(text="")
    return RawSeatDesk(children, location={"x": 40, "y": y})


@pytest.mark.asyncio
async def test_full_rescan_does_not_reuse_a_user_read_occupied_on_another_seat():
    """重扫不许把「读不到昵称的占座」直接沿用上一轮的占座者。

    真机（09-27 21:58:43）：第三排一直不可见，快照里 9 号位挂着 Outlier。把
    Outlier 挪到 11 号、Chainer 坐到 9 号后，专注人数背离触发全量重扫：9 号位读到
    占座但昵称读不出来，代码沿用了快照里的 Outlier，而 11 号位从 label 读到
    Outlier —— 同一个人同时占两个麦位，Chainer 的上座被这次「权威」扫描吞掉。
    """
    desks = [
        _raw_desk_sides(("1", False), ("2", False), 100),
        _raw_desk_sides(("3", False), ("4", False), 200),
        _raw_desk_sides(("5", False), ("6", False), 300),
        _raw_desk_sides(("7", False), ("8", False), 400),
        # 9 号：Chainer 刚落座，这一轮昵称还没渲染出来；10 号 Joyer 可读
        _raw_desk_sides(("", True), ("Joyer", True), 500),
        # 11 号 Outlier（label 直接读到），12 号空位
        _raw_desk_sides(("Outlier", True), ("12", False), 600),
    ]
    handler = make_handler(desks=desks)
    manager = SeatObservationManager.initialize(handler)
    manager._seat_ui = FakeSeatUI(desks=desks)

    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="Chainer", label="Chainer")
    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Outlier", label="Outlier")
    manager.seats[10] = SeatSlot(seat_number=10, occupied=True, username="Joyer", label="Joyer")

    # 认出 9 号位新占座者的唯一手段是点头像读弹窗
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: "Chainer" if seat_number == 9 else None
    )

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        await manager.expand_rescan_and_collapse(3)

    assert manager._last_rescan_ok is True
    assert manager.seats[11].username == "Outlier"
    # 9 号位不能沿用已经坐在 11 号位的人
    assert manager.seats[9].username == "Chainer"
    assert 9 in [c.args[2] for c in manager.inspect_occupant.await_args_list]

    # 铁律：一个用户同一时刻只能占一个麦位
    seated = [s.username for s in manager.seats.values() if s.occupied and s.username]
    assert len(seated) == len(set(seated))




def _ghost_render_desks():
    """真机 22:29:31 的读数：1/9/10/11 在座 = 4 人，而专注人数说 3。

    9 号位的 Chainer 其实已经下座，面板还挂着他的残留 label —— 重扫把他读成在座。
    """
    return [
        _raw_desk_sides(("斯德哥尔摩情人", True), ("2", False), 100),
        _raw_desk_sides(("3", False), ("4", False), 200),
        _raw_desk_sides(("5", False), ("6", False), 300),
        _raw_desk_sides(("7", False), ("8", False), 400),
        _raw_desk_sides(("Chainer", True), ("Joyer", True), 500),
        _raw_desk_sides(("Outlier", True), ("12", False), 600),
    ]


def _manager_for_rescan(desks):
    handler = make_handler(desks=desks)
    manager = SeatObservationManager.initialize(handler)
    manager._seat_ui = FakeSeatUI(desks=desks)
    manager.inspect_occupant = AsyncMock(return_value=None)
    # _reconcile_focus_count 是「先登记再扫」的，进扫描时这个取值已经登记过了
    manager._reconciled_focus_count = 3
    return manager


@pytest.mark.asyncio
async def test_rescan_disagreeing_with_focus_count_reopens_the_ledger():
    """重扫落地不等于对上账：读出 4 个在座 vs 专注 3 人时，必须把账挂回去。

    旧实现只在扫描**失败**时撤登记，自相矛盾的结论照样算成功，这份带鬼的表格要用到
    专注人数下次变化为止。
    """
    desks = _ghost_render_desks()
    manager = _manager_for_rescan(desks)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.expand_rescan_and_collapse(3)

    assert manager._last_rescan_ok is True
    assert sum(1 for s in manager.seats.values() if s.occupied) == 4
    assert manager._reconciled_focus_count is None
    assert manager._consistency_retry_due is True
    warnings = [str(c) for c in manager.logger.warning.call_args_list]
    assert any("4 seats occupied but focus count is 3" in w for w in warnings)


@pytest.mark.asyncio
async def test_consistency_retry_stops_when_readings_are_identical():
    """补扫的正当性来自「面板会重绘」；读数一模一样时再扫也只会得到同一份答案。"""
    desks = _ghost_render_desks()
    manager = _manager_for_rescan(desks)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.expand_rescan_and_collapse(3)
        assert manager._consistency_retry_due is True

        # 下一轮：账重新登记上，补扫一次，读数分毫未动
        manager._reconciled_focus_count = 3
        await manager.expand_rescan_and_collapse(3)

    assert manager._consistency_retry_due is False
    # 不再撤登记 —— 没有新信息就一直补扫就是展开收起死循环
    assert manager._reconciled_focus_count == 3
    warnings = [str(c) for c in manager.logger.warning.call_args_list]
    assert any("byte-identical readings" in w for w in warnings)


@pytest.mark.asyncio
async def test_consistent_rescan_leaves_the_ledger_closed():
    """对上了就不许留欠账，否则每次重扫都会多追一次展开。"""
    desks = _ghost_render_desks()
    handler = make_handler(desks=desks)
    manager = SeatObservationManager.initialize(handler)
    manager._seat_ui = FakeSeatUI(desks=desks)
    manager.inspect_occupant = AsyncMock(return_value=None)
    manager._reconciled_focus_count = 4

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.expand_rescan_and_collapse(4)

    assert sum(1 for s in manager.seats.values() if s.occupied) == 4
    assert manager._consistency_retry_due is False
    assert manager._reconciled_focus_count == 4


@pytest.mark.asyncio
async def test_partial_coverage_rescan_does_not_claim_inconsistency():
    """只读到一部分位子时，「在座数 != 专注数」不算矛盾 —— 差的可能正是没看见的。"""
    desks = [
        _raw_desk_sides(("斯德哥尔摩情人", True), ("2", False), 100),
        _raw_desk_sides(("3", False), ("4", False), 200),
    ]
    manager = _manager_for_rescan(desks)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.expand_rescan_and_collapse(3)

    assert manager._consistency_retry_due is False
    assert manager._reconciled_focus_count == 3


@pytest.mark.asyncio
async def test_consistency_retry_uses_the_longer_cooldown():
    """补扫要 10 秒后才允许，常规重扫 3 秒就行：一次展开要十几秒，不能追着扫。"""
    clock = FakeClock()
    policy = SeatRescanCooldownPolicy(time_fn=clock)
    manager = SeatObservationManager.initialize(make_handler(), cooldown_policy=policy)
    manager._last_rescan_ok = True
    manager._last_rescan_time = clock()

    clock.advance(5.0)  # 5 秒过去：> 3.0s (常规冷却已过)，但 < 10.0s (补扫冷却未到)

    manager._consistency_retry_due = True
    with patch.object(
        manager, "expand_rescan_and_collapse", new_callable=AsyncMock
    ) as scan:
        assert await manager._request_full_scan(target_focus=3, reason="retry") is False
    scan.assert_not_awaited()

    manager._consistency_retry_due = False
    with patch.object(
        manager, "expand_rescan_and_collapse", new_callable=AsyncMock
    ) as scan:
        assert await manager._request_full_scan(target_focus=3, reason="normal") is True
    scan.assert_awaited_once()




def _raw_desk_evidence(left: dict, right: dict, y: int) -> RawSeatDesk:
    """按 DOM 证据逐侧构造 raw desk：{"label":..,"state":..,"default":..,"rank":..}。

    侧里什么都不给 = 真机上那种「这一轮什么都没渲染出来」的空读数（23:00:0x 的 9 号位）。
    """
    elements = soul_elements()
    children = {}
    for side, spec in (("left", left), ("right", right)):
        if "label" in spec:
            children[elements[f"{side}_label"]] = SimpleNamespace(text=spec["label"])
        if spec.get("state"):
            children[elements[f"{side}_state"]] = SimpleNamespace(text="")
        if spec.get("default"):
            children[elements[f"{side}_default_name"]] = SimpleNamespace(text="点击入座")
        if spec.get("rank"):
            children[elements[f"{side}_rank"]] = SimpleNamespace(text="")
    return RawSeatDesk(children, location={"x": 40, "y": y})


_EMPTY = {"default": True}
_EMPTY_ROW = [(_EMPTY, _EMPTY) for _ in range(4)]


def _two_phase_desks(top_row3, bottom_row3):
    """同一间房的两个相位读数：前两排（d0~d3）恒为空座，第三排两个相位给不同证据。"""
    ys = [100, 300, 500, 700, 900, 1100]
    top = [_raw_desk_evidence(l, r, y) for (l, r), y in zip(_EMPTY_ROW + top_row3, ys)]
    bottom = [_raw_desk_evidence(l, r, y) for (l, r), y in zip(_EMPTY_ROW + bottom_row3, ys)]
    return top, bottom


@pytest.mark.asyncio
async def test_rescan_keeps_the_informative_of_two_passes_for_one_seat():
    """同一个位子读两次：什么都没读到的那次，不许盖掉读到明确空座的那次。

    真机 23:00:0x：顶相位 9 号位 L:{state=0 label='' default=0 rank=0 occupied=0}（没渲染
    出来），底相位同一个位子 L:{default=1 empty=1}（点击入座 = 明确空座）。旧合并规则只
    认「新读数占座」和「新读数有昵称」两种升级，两条都不成立 → 留下空读数 →
    _apply_snapshot 对「既非占座也非空座」一律保留旧值 → 早就不在位子上的人永远挂在
    9 号位上，账也永远对不上（专注 1 vs 在座 2），座次表更不会因为「有变更」而输出。
    """
    top, bottom = _two_phase_desks(
        [({}, {"rank": True}), (_EMPTY, _EMPTY)],
        [({"default": True}, {"label": "群主", "state": True}), (_EMPTY, _EMPTY)],
    )
    handler = make_handler(desks=top)
    handler.element_finder.find_elements = MagicMock(side_effect=[top, bottom])
    manager = SeatObservationManager.initialize(handler)
    manager._seat_ui = FakeSeatUI(desks=top)
    manager.inspect_occupant = AsyncMock(return_value=None)
    manager._reconciled_focus_count = 1

    # 扫描前的快照：9 号位挂着已经走掉的人，10 号位是群主 —— 已知在座 2 人
    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Chainer", label="Chainer")
    manager.seats[10] = SeatSlot(seat_number=10, occupied=True, username="群主", label="群主", is_owner=True)

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        await manager.expand_rescan_and_collapse(1)

    assert manager.seats[9].occupied is False, "底相位的明确空座必须赢过顶相位的空读数"
    assert manager.seats[9].username is None
    assert manager.seats[10].username == "群主"
    # 鬼清掉之后 1 在座 == 专注 1，账对上，不该欠补扫
    assert manager._consistency_retry_due is False
    assert manager._reconciled_focus_count == 1
    assert notify.await_args.kwargs["seat_info"]["Chainer"] == {
        "seat_number": 9,
        "action": "leave_seat",
    }


@pytest.mark.asyncio
async def test_landed_rescan_prints_the_seat_table_even_with_no_changes():
    """重扫是十几秒的主动行为，落地就得给出结论 —— 没变更也得打印，否则无从核对。

    真机 23:00:0x：扫描跑完、一个字节都没输出（has_changes 为假），没人能判断「1 个
    专注」到底坐在哪。
    """
    top, bottom = _two_phase_desks(
        [({"default": True}, {"label": "群主", "state": True}), (_EMPTY, _EMPTY)],
        [({"default": True}, {"label": "群主", "state": True}), (_EMPTY, _EMPTY)],
    )
    handler = make_handler(desks=top)
    handler.element_finder.find_elements = MagicMock(side_effect=[top, bottom])
    manager = SeatObservationManager.initialize(handler)
    manager._seat_ui = FakeSeatUI(desks=top)
    manager.inspect_occupant = AsyncMock(return_value=None)
    manager.seats[10] = SeatSlot(
        seat_number=10, occupied=True, username="群主", label="群主", is_owner=True
    )

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        changed = await manager.expand_rescan_and_collapse(1)

    assert changed is False  # 确实没有变更
    tables = [c.args[0] for c in manager.logger.info.call_args_list if c.args]
    assert any("[FocusSeatObservation]" in t for t in tables), "扫描落地必须报出座次表"




def test_seat_table_colors_occupants_and_marks_changed_seats_differently():
    """座次表着色：在座亮青、本轮变更亮绿、空闲压暗 —— 纯文本内容不许变。"""
    from ushareiplay.core.log_formatter import strip_ansi

    manager = SeatObservationManager.initialize(None)
    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Outlier")
    manager.seats[10] = SeatSlot(seat_number=10, occupied=True, username="Joyer")
    manager.seats[11] = SeatSlot(seat_number=11, occupied=False)

    layout = manager.format_3row_layout("测试触发", changed_seats={9})

    assert "第三排: [9号: Outlier] [10号: Joyer]  |  [11号: 空闲] [12号: 空闲]" in strip_ansi(layout)
    assert f"{SeatObservationManager.SEAT_COLOR_CHANGED}[9号: Outlier]" in layout
    assert f"{SeatObservationManager.SEAT_COLOR_OCCUPIED}[10号: Joyer]" in layout
    assert f"{SeatObservationManager.SEAT_COLOR_IDLE}[11号: 空闲]" in layout


def test_rescan_table_highlights_only_the_seats_that_actually_changed():
    """变更位子的着色必须来自真 diff，不是「凡是坐了就标绿」。"""
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.seats[9] = SeatSlot(seat_number=9, occupied=True, username="Chainer", label="Chainer")

    observed = {
        9: (None, "left", {"occupied": True, "is_empty": False, "label": "Chainer",
                           "username": "Chainer", "is_owner": False}),
        10: (None, "right", {"occupied": True, "is_empty": False, "label": "Joyer",
                             "username": "Joyer", "is_owner": False}),
    }
    old_slots = {k: v.copy() for k, v in manager.seats.items()}
    changed = manager._changed_seat_numbers(old_slots, manager.seats, set(observed))
    assert changed == {10} or changed == set()  # 10 号本轮新占座；9 号没动

    manager.seats[10] = SeatSlot(seat_number=10, occupied=True, username="Joyer", label="Joyer")
    changed = manager._changed_seat_numbers(old_slots, manager.seats, set(observed))
    assert changed == {10}


def test_mark_owner_seated_move_reseats_without_double_booking_or_inflated_count():
    """房主换座：先腾出旧位子，专注人数不变。

    真机 09-28 18:07:08：Joyer 原本坐 10 号（18:07:07 视口同步读到 10号=群主），
    :seat 2 11 是一次 10→11 的移动。mark_owner_seated 却不清旧位、无条件把
    专注数 +1 写进 RoomState（18:07:08 那条「Focus count updated: 1 -> 2」是它
    凭空写的，房间真实文案始终是 1 人专注中）。快照里同一个人占两座、账面人数
    虚增，紧接着的被动观测就拿真实人数 1 去比对 2，误判背离、引爆整轮全量重扫。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager._last_focus_count = 1
    manager.seats[10] = SeatSlot(
        seat_number=10, occupied=True, username="群主", label="群主", is_owner=True
    )

    manager.mark_owner_seated(11)

    assert manager.seats[10].occupied is False
    assert manager.seats[10].username is None
    assert manager.seats[11].occupied is True
    assert manager.seats[11].is_owner is True
    # 换座净人数为 0：基准不许动，对账标记跟着基准走
    assert manager._last_focus_count == 1
    assert manager._reconciled_focus_count == 1
    assert sum(1 for s in manager.seats.values() if s.occupied) == 1


@pytest.mark.asyncio
async def test_owner_ghost_render_cannot_book_the_room_owner_on_two_seats():
    """「群主」身份文字必须归一为配置的房主昵称，一人一麦位闸才看得见矛盾。

    真机 09-28 18:07:12–18:08:00：Joyer 移到 11 号后，面板 9 号位仍挂着她的残留
    渲染（重扫点头像弹窗读出的就是 Joyer 本人），11 号位 label 渲染为「群主」。
    _extract_seat_info 把「群主」原样当身份，_claimed_usernames 的比对字符串是
    "Joyer" != "群主"，「一人一麦位」闸对这个人的两座登记完全失明 —— 表格落成
    [9号: Joyer] + [11号: 群主]，专注人数 1 对两个人，连续两轮重扫字节相同后
    按「等新信息」把这份鬼表格锁死在快照里。
    """
    desks = [
        _raw_desk_sides(("1", False), ("2", False), 100),
        _raw_desk_sides(("3", False), ("4", False), 200),
        _raw_desk_sides(("5", False), ("6", False), 300),
        _raw_desk_sides(("7", False), ("8", False), 400),
        # 9 号：房主移走后的残留渲染 —— 读到占座、label 空，弹窗是她本人；10 号空
        _raw_desk_sides(("", True), ("10", False), 500),
        # 11 号：真实落座处，label 渲染为身份文字「群主」；12 号空
        _raw_desk_sides(("群主", True), ("12", False), 600),
    ]
    handler = make_handler(desks=desks)
    handler.config["room_owner"] = "Joyer"
    manager = SeatObservationManager.initialize(handler)
    manager._seat_ui = FakeSeatUI(desks=desks)
    manager._reconciled_focus_count = 1
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: "Joyer" if seat_number == 9 else None
    )

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
        await manager.expand_rescan_and_collapse(1)

    assert manager._last_rescan_ok is True
    # 「群主」身份归一为配置房主昵称
    assert manager.seats[11].username == "Joyer"
    assert manager.seats[11].is_owner is True
    assert manager.seats[11].occupied is True
    # 残留位头像是房主本人但房主已落座 11 号：判定为残留渲染（ghost），清空为空座
    assert manager.seats[9].occupied is False
    assert manager.seats[9].username is None
    # 房间真实在座人数与专注人数 1 完全自洽，不欠补扫
    assert sum(1 for s in manager.seats.values() if s.occupied) == 1
    assert manager._consistency_retry_due is False
    assert manager._reconciled_focus_count == 1
    confirmed = [
        n for n, s in manager.seats.items()
        if s.occupied and s.username in ("Joyer", "群主")
    ]
    assert confirmed == [11]
    warnings = [str(c) for c in handler.logger.warning.call_args_list]
    assert any("another seat this round" in w or "identity conflict" in w for w in warnings)


@pytest.mark.asyncio
async def test_seat_identity_collision_in_snapshot_resolves_to_winner_and_clears_ghost():
    """同一次观测快照中若同一昵称出现在两个麦位，证据更强的麦位保留，冲突麦位清空为空座。

    复现真机 09-28 21:04:27 现场：Joyer 读在 9 和 11 号位。
    11 号位有「群主」身份及 is_owner 强证据，9 号位无 label 仅有占座。
    快照必须将 11 号保留为 Joyer，9 号清空为 occupied=False，
    避免虚增在座人数导致 Rescan still disagrees with focus count (2 seated vs 1)。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)

    # 构造一次观测：9 号位与 11 号位均被读成 Joyer
    observed = {
        9: (MagicMock(), "left", {
            "occupied": True,
            "username": "Joyer",
            "label": "",
            "is_owner": False,
            "is_empty": False,
        }),
        11: (MagicMock(), "left", {
            "occupied": True,
            "username": "Joyer",
            "label": "群主",
            "is_owner": True,
            "is_empty": False,
        }),
    }
    for n in range(1, 13):
        if n not in observed:
            observed[n] = (MagicMock(), "left", {
                "occupied": False,
                "username": None,
                "label": f"{n}",
                "is_owner": False,
                "is_empty": True,
            })

    manager._apply_snapshot(observed)

    # 11 号位证据强（is_owner=True, label="群主"），保留落座
    assert manager.seats[11].occupied is True
    assert manager.seats[11].username == "Joyer"
    assert manager.seats[11].is_owner is True

    # 9 号位作为冲突残留位被清空
    assert manager.seats[9].occupied is False
    assert manager.seats[9].username is None
    assert manager.seats[9].is_owner is False

    # 账面总在座人数为 1
    assert sum(1 for s in manager.seats.values() if s.occupied) == 1

    # observed 字典中的 info 也同步被置为 empty
    assert observed[9][2]["occupied"] is False
    assert observed[9][2]["is_empty"] is True


def test_format_3row_layout_with_room_admins():
    from ushareiplay.core.log_formatter import strip_ansi
    from ushareiplay.managers.admin_manager import AdminManager

    AdminManager.reset_instance()
    admin_mgr = AdminManager.initialize()
    admin_mgr.add_room_admin("AdminAlice")
    admin_mgr.add_room_admin("OwnerUser")  # Owner is also in room admins

    manager = SeatObservationManager.initialize(None)
    # Seat 1: Owner with username
    manager.seats[1] = SeatSlot(seat_number=1, occupied=True, username="OwnerUser", is_owner=True)
    # Seat 2: Owner without distinct username
    manager.seats[2] = SeatSlot(seat_number=2, occupied=True, username="群主", is_owner=True)
    # Seat 3: Admin with username
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="AdminAlice")
    # Seat 4: Admin by label only (no username)
    manager.seats[4] = SeatSlot(seat_number=4, occupied=True, label="管理")
    # Seat 5: Admin by label and username
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, label="管理", username="AdminBob")
    # Seat 6: Admin by label where username is "管理"
    manager.seats[6] = SeatSlot(seat_number=6, occupied=True, label="管理", username="管理")
    # Seat 7: Normal user
    manager.seats[7] = SeatSlot(seat_number=7, occupied=True, username="NormalUser")
    # Seat 8: Occupied without username/label
    manager.seats[8] = SeatSlot(seat_number=8, occupied=True)
    # Seat 9: Empty
    manager.seats[9] = SeatSlot(seat_number=9, occupied=False)

    layout = manager.format_3row_layout("测试管理员标记", changed_seats={3})
    lines = strip_ansi(layout).splitlines()

    # Owner priority preserved
    assert "[1号: 群主(OwnerUser)]" in lines[1]
    assert "[2号: 群主]" in lines[1]
    # Admin formats
    assert "[3号: 管理(AdminAlice)]" in lines[1]
    assert "[4号: 管理]" in lines[1]
    assert "[5号: 管理(AdminBob)]" in lines[2]
    assert "[6号: 管理]" in lines[2]
    # Normal user and empty
    assert "[7号: NormalUser]" in lines[2]
    assert "[8号: 已占用]" in lines[2]
    assert "[9号: 空闲]" in lines[3]

    # ANSI colors
    assert f"{manager.SEAT_COLOR_CHANGED}[3号: 管理(AdminAlice)]{manager.SEAT_COLOR_RESET}" in layout
    assert f"{manager.SEAT_COLOR_OCCUPIED}[4号: 管理]{manager.SEAT_COLOR_RESET}" in layout
    assert f"{manager.SEAT_COLOR_IDLE}[9号: 空闲]{manager.SEAT_COLOR_RESET}" in layout


def test_get_user_seat_and_all_seated_users():
    manager = SeatObservationManager.initialize(None)
    manager.seats[3] = SeatSlot(seat_number=3, occupied=True, username="Alice")
    manager.seats[5] = SeatSlot(seat_number=5, occupied=True, username="Bob")
    manager.seats[7] = SeatSlot(seat_number=7, occupied=False, username="Charlie")  # not occupied

    assert manager.get_user_seat("Alice") == 3
    assert manager.get_user_seat("Bob") == 5
    assert manager.get_user_seat("Charlie") is None
    assert manager.get_user_seat("David") is None
    assert manager.get_user_seat("") is None
    assert manager.get_user_seat(None) is None

    assert manager.get_all_seated_users() == {"Alice": 3, "Bob": 5}


# ---------------------------------------------------------------------------
# 可视范围内换座的检测（真机 09-29 11:40~11:41 / 09-28 21:33:57 现场）
#
# 真机麦位 DOM 的关键事实（tests/fixtures/seat_dom/ 的 dump）：普通用户占座时
# TvLabelH 渲染的是**麦位编号**，昵称根本不在 DOM 里，只能点头像弹窗读
# （inspect_occupant）。所以「换座」在视口里的形状永远是：
#   旧位子：ClState + 编号 label（残留渲染）或「点击入座」（已重绘）
#   新位子：ClState + 编号 label，昵称要靠弹窗
# ---------------------------------------------------------------------------


def _moved_within_viewport_desks(handler):
    """Outlier 从 12 号换到 11 号，12 号位还挂着残留渲染。"""
    return [
        build_live_desk_wrapper(handler, (9, False, None), (10, False, None), y=300),
        build_live_desk_wrapper(handler, (11, True, None), (12, True, None), y=600),
    ]


@pytest.mark.asyncio
async def test_in_viewport_move_with_residual_render_is_not_swallowed_by_stale_inheritance():
    """可视范围内换座必须被检测到：弹窗的本轮证据不许被上一轮快照判成"残留"。

    真机 09-29 11:40:5x：Outlier 在 12 号位（快照），换到 11 号后 12 号仍渲染成占座。
    旧逻辑先拿快照把 Outlier 沿用给 12 号（本轮并没有读到他的身份），再点头像弹窗
    在 11 号读出 Outlier，于是"11 号的人本轮已别处落座"成立，把**真正的新位子**
    当成 ghost 清空 —— 快照原地不动、没有座次表、没有 move_seat 事件，
    可视范围内换座被整个吞掉。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.seats[12] = SeatSlot(seat_number=12, occupied=True, username="Outlier", label="Outlier")
    # 真机：11 号位点头像弹窗读出 Outlier；12 号位的残留渲染弹窗同样是他
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: "Outlier" if seat_number in (11, 12) else None
    )

    desks = _moved_within_viewport_desks(handler)
    with patch.object(manager, "_request_full_scan", new_callable=AsyncMock) as rescan:
        rescan.return_value = True
        await manager.observe_visible_desks(desks)

    # 本轮弹窗读到的身份不能被撤销成空座：11 号位仍然是占座
    assert manager.seats[11].occupied is not True or manager.seats[11].username == "Outlier"
    # 去向不明的变更必须升级为全量重扫，而不是"当作没发生"
    assert rescan.await_count == 1, "可视范围内换座被静默吞掉：没有任何重扫/事件"
    assert "contested" in rescan.await_args.kwargs["reason"] or "unknown destination" in rescan.await_args.kwargs["reason"]


@pytest.mark.asyncio
async def test_full_rescan_lands_an_in_viewport_move_and_reports_move_seat():
    """权威重扫必须把可视范围内的换座落到快照并发出 move_seat（12 号→11 号）。

    这是用户看到的最终结果：座次表从 [12号: Outlier] 变成 [11号: Outlier]，
    并且联动命令拿到 action=move_seat。旧逻辑在重扫里同样先沿用旧快照把 Outlier
    钉在 12 号，再把 11 号的本轮弹窗证据判成残留清空 —— 重扫也检不出来。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    desks = [
        build_live_raw_desk((1, False, None), (2, False, None), y=100),
        build_live_raw_desk((3, False, None), (4, False, None), y=200),
        build_live_raw_desk((5, False, None), (6, False, None), y=300),
        build_live_raw_desk((7, False, None), (8, False, None), y=400),
        build_live_raw_desk((9, False, None), (10, False, None), y=500),
        # 11 号：本轮真实落座处；12 号：换座后还没重绘的残留渲染
        build_live_raw_desk((11, True, None), (12, True, None), y=600),
    ]
    handler.element_finder.find_elements = MagicMock(return_value=desks)
    manager._seat_ui = FakeSeatUI(desks=desks)
    manager.seats[12] = SeatSlot(seat_number=12, occupied=True, username="Outlier", label="Outlier")
    manager._last_focus_count = 1
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: "Outlier" if seat_number in (11, 12) else None
    )

    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.expand_rescan_and_collapse(1)

    assert manager._last_rescan_ok is True
    assert changed is True, "换座必须被判成有变更"
    assert manager.seats[11].occupied is True and manager.seats[11].username == "Outlier"
    assert manager.seats[12].occupied is False, "旧位子（残留渲染）必须腾出来"
    kwargs = notify.call_args.kwargs
    assert kwargs["seat_info"]["Outlier"] == {"seat_number": 11, "action": "move_seat"}
    # 一人一麦位：不许同时占两座
    assert sum(1 for s in manager.seats.values() if s.occupied) == 1


@pytest.mark.asyncio
async def test_in_viewport_move_without_residual_render_is_applied_directly():
    """旧位子已重绘成空座时，视口内换座应当直接配对落快照并发出 move_seat。

    真机 09-28 21:33:57 的形状：Chainer 从 12 号换到 11 号，12 号渲染成「点击入座」。
    这条路径不依赖重扫，是换座检测最便宜也最常见的形状，必须钉住。
    """
    handler = make_handler()
    manager = SeatObservationManager.initialize(handler)
    manager.seats[12] = SeatSlot(seat_number=12, occupied=True, username="Chainer", label="Chainer")
    manager.inspect_occupant = AsyncMock(
        side_effect=lambda desk, side, seat_number: "Chainer" if seat_number == 11 else None
    )

    desks = [
        build_live_desk_wrapper(handler, (9, False, None), (10, False, None), y=300),
        build_live_desk_wrapper(handler, (11, True, None), (12, False, None), y=600),
    ]
    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
        notify = AsyncMock()
        cmd_mgr.return_value.notify_focus_count_change = notify
        changed = await manager.observe_visible_desks(desks)

    assert changed is True
    assert manager.seats[11].username == "Chainer"
    assert manager.seats[12].occupied is False
    assert notify.call_args.kwargs["seat_info"]["Chainer"] == {
        "seat_number": 11,
        "action": "move_seat",
    }


def test_seat_rescan_cooldown_policy_defaults():
    policy = SeatRescanCooldownPolicy()
    assert policy.rescan_cooldown == 3.0
    assert policy.rescan_retry_cooldown == 30.0
    assert policy.consistency_rescan_cooldown == 10.0
    assert SeatObservationManager.RESCAN_COOLDOWN == 3.0
    assert SeatObservationManager.RESCAN_RETRY_COOLDOWN == 30.0
    assert SeatObservationManager.CONSISTENCY_RESCAN_COOLDOWN == 10.0


@pytest.mark.asyncio
async def test_rescan_invariants_with_injected_cooldown_policy():
    """三条不变量以时序断言验证：
    1. 同一份读数只触发一次全量重扫；
    2. 冷却未到不重扫；
    3. 重扫未真正落地则留下一次补扫欠账。
    """
    clock = FakeClock(100.0)
    policy = SeatRescanCooldownPolicy(
        rescan_cooldown=5.0,
        rescan_retry_cooldown=20.0,
        consistency_rescan_cooldown=15.0,
        time_fn=clock,
    )
    manager = SeatObservationManager.initialize(make_handler(), cooldown_policy=policy)

    scan_calls = []

    async def _mock_scan(focus):
        scan_calls.append(focus)
        manager._last_rescan_ok = True

    manager.expand_rescan_and_collapse = _mock_scan

    fingerprint_a = frozenset([("left", "userA"), ("right", "userB")])

    # 1. 首次触发：成功执行
    res1 = await manager._request_full_scan(
        target_focus=2, reason="scan_1", fingerprint=fingerprint_a
    )
    assert res1 is True
    assert len(scan_calls) == 1

    # 2. 不变量 2：冷却未到不重扫 (只过了 2 秒，< 5.0)
    clock.advance(2.0)
    res2 = await manager._request_full_scan(
        target_focus=2, reason="scan_too_soon", fingerprint=fingerprint_a
    )
    assert res2 is False
    assert len(scan_calls) == 1

    # 3. 冷却过了 (再过 4 秒，总计 6s > 5.0)，但是指纹未变：不变量 1：同一份读数只触发一次重扫
    clock.advance(4.0)
    # 模拟视口传入相同指纹：
    # Note: _request_full_scan 自身如果传入同指纹，会被 _scanned_seat_change_fingerprint 或上一层拦截
    assert manager._scanned_seat_change_fingerprint == fingerprint_a

    # 新读数指纹：允许触发重扫
    fingerprint_b = frozenset([("left", "userC")])
    res3 = await manager._request_full_scan(
        target_focus=3, reason="scan_new_fp", fingerprint=fingerprint_b
    )
    assert res3 is True
    assert len(scan_calls) == 2

    # 4. 不变量 3：重扫未真正落地则留下一次补扫欠账（撤掉指纹标记，冷却放宽到 retry_cooldown）
    async def _failing_scan(focus):
        scan_calls.append(focus)
        manager._last_rescan_ok = False

    manager.expand_rescan_and_collapse = _failing_scan
    clock.advance(10.0)

    fingerprint_c = frozenset([("left", "userD")])
    res4 = await manager._request_full_scan(
        target_focus=4, reason="scan_failing", fingerprint=fingerprint_c
    )
    assert res4 is True
    assert len(scan_calls) == 3
    # 失败后指纹撤回
    assert manager._scanned_seat_change_fingerprint is None

    # retry 冷却为 20.0，前进 10 秒（未到 20.0）不能扫
    clock.advance(10.0)
    res5 = await manager._request_full_scan(
        target_focus=4, reason="retry_too_soon", fingerprint=fingerprint_c
    )
    assert res5 is False
    assert len(scan_calls) == 3

    # 前进再过 11 秒（总计 21.0 > 20.0），补扫可以执行
    clock.advance(11.0)
    res6 = await manager._request_full_scan(
        target_focus=4, reason="retry_landing", fingerprint=fingerprint_c
    )
    assert res6 is True
    assert len(scan_calls) == 4


def test_gate_state_unified_reset():
    """验证 11 个协调字段可通过 reset() 单动作整体重置回初始值。"""
    state = SeatObservationGateState()
    assert state.last_focus_count is None
    assert state.reconciled_focus_count is None
    assert state.scanned_seat_change_fingerprint is None
    assert state.last_rescan_ok is False
    assert state.last_rescan_time == 0.0
    assert state.last_visible_band is None
    assert state.band_change_reason is None
    assert state.residual_seats == {}
    assert state.last_scan_fingerprint is None
    assert state.consistency_retry_due is False
    assert isinstance(state.lock, asyncio.Lock)

    # 脏化全部 11 个字段
    state.last_focus_count = 5
    state.reconciled_focus_count = 5
    state.scanned_seat_change_fingerprint = frozenset([("a", "b")])
    state.last_rescan_ok = True
    state.last_rescan_time = 123.45
    state.last_visible_band = ("band", 1)
    state.band_change_reason = "reason"
    state.residual_seats = {1: "user1"}
    state.last_scan_fingerprint = frozenset([("c", "d")])
    state.consistency_retry_due = True
    old_lock = state.lock

    # 单动作重置
    state.reset()

    assert state.last_focus_count is None
    assert state.reconciled_focus_count is None
    assert state.scanned_seat_change_fingerprint is None
    assert state.last_rescan_ok is False
    assert state.last_rescan_time == 0.0
    assert state.last_visible_band is None
    assert state.band_change_reason is None
    assert state.residual_seats == {}
    assert state.last_scan_fingerprint is None
    assert state.consistency_retry_due is False
    assert state.lock is not old_lock


def test_gate_state_integration_with_manager_clear():
    """验证 SeatObservationManager.clear() 委托 gate_state.reset() 重置全部闸门。"""
    manager = SeatObservationManager.initialize(None)
    manager._last_focus_count = 3
    manager._reconciled_focus_count = 3
    manager._last_rescan_ok = True
    manager._last_rescan_time = 999.0
    manager._residual_seats = {12: "Alice"}
    manager._consistency_retry_due = True
    manager.seats[1].occupied = True

    assert manager.gate_state.last_focus_count == 3
    assert manager.gate_state.residual_seats == {12: "Alice"}

    manager.clear()

    assert manager.gate_state.last_focus_count is None
    assert manager.gate_state.reconciled_focus_count is None
    assert manager.gate_state.last_rescan_ok is False
    assert manager.gate_state.last_rescan_time == 0.0
    assert manager.gate_state.residual_seats == {}
    assert manager.gate_state.consistency_retry_due is False
    assert manager.seats[1].occupied is False


