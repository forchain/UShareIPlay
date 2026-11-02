import asyncio
from types import SimpleNamespace
import pytest

from ushareiplay.managers.seat_manager.seat_panel_reader import (
    Reading,
    SeatPanelReader,
)
from tests.seat_fixtures import (
    FakeController,
    LIVE_DESK_ORIGIN,
    LIVE_DESK_SIZE,
    build_desk_wrapper,
    build_real_desk_wrappers,
    make_handler,
    RawSeatDesk,
    ClickableNode,
)


def test_reading_dataclass_contract():
    """Reading 必须是不可变三态值对象。"""
    r_occ = Reading(
        occupied=True,
        is_empty=False,
        label="Alice",
        has_state=True,
        has_default=False,
        has_rank=False,
        avatar_images=2,
    )
    assert r_occ.occupied is True
    assert r_occ.is_empty is False
    assert r_occ.readable is True

    r_empty = Reading(
        occupied=False,
        is_empty=True,
        label="1",
        has_state=False,
        has_default=False,
        has_rank=False,
        avatar_images=1,
    )
    assert r_empty.occupied is False
    assert r_empty.is_empty is True
    assert r_empty.readable is True

    r_unknown = Reading(
        occupied=False,
        is_empty=False,
        label="",
        has_state=False,
        has_default=False,
        has_rank=False,
        avatar_images=0,
    )
    assert r_unknown.occupied is False
    assert r_unknown.is_empty is False
    assert r_unknown.readable is False

    with pytest.raises(Exception):
        r_occ.occupied = False  # frozen dataclass


def test_tap_point_hardcoded_1080p_geometry_pin():
    """硬编码钉住 1080p 几何计算坐标，防止公式漂移。

    桌位原点 (28, 566)，尺寸 (309, 207)：
    - left:  x = 28 + (309 // 4) = 28 + 77 = 105, y = 566 + (207 // 2) = 566 + 103 = 669 -> (105, 669)
    - right: x = 28 + (3 * 309 // 4) = 28 + 231 = 259, y = 566 + 103 = 669 -> (259, 669)
    """
    reader = SeatPanelReader()
    desk = SimpleNamespace(
        bounds={
            "x": LIVE_DESK_ORIGIN[0],
            "y": LIVE_DESK_ORIGIN[1],
            "width": LIVE_DESK_SIZE[0],
            "height": LIVE_DESK_SIZE[1],
        }
    )

    left_pt = reader.tap_point(desk, "left")
    right_pt = reader.tap_point(desk, "right")

    assert left_pt == (105, 669)
    assert right_pt == (259, 669)


def test_tap_point_and_where_missing_bounds():
    reader = SeatPanelReader()
    desk_no_bounds = SimpleNamespace()
    assert reader.tap_point(desk_no_bounds, "left") is None
    assert reader.where(desk_no_bounds, "left") is None

    desk_zero_bounds = SimpleNamespace(bounds={"x": 10, "y": 20, "width": 0, "height": 0})
    assert reader.tap_point(desk_zero_bounds, "left") is None
    assert reader.where(desk_zero_bounds, "left") is None


def test_where_prefers_seat_bounds():
    reader = SeatPanelReader()
    seat_elem = SimpleNamespace(bounds={"x": 60, "y": 573, "width": 135, "height": 167})
    desk = SimpleNamespace(
        bounds={"x": 28, "y": 566, "width": 309, "height": 207},
        left_seat=seat_elem,
    )
    # seat_bounds center: 60 + 135//2 = 127, 573 + 167//2 = 656
    assert reader.where(desk, "left") == (127, 656)
    # right_seat is absent -> falls back to tap_point (259, 669)
    assert reader.where(desk, "right") == (259, 669)


def test_read_real_fixture_desks():
    """验证真实真机 dump fixture 的读数。"""
    handler = make_handler()
    reader = SeatPanelReader(handler)

    desks = build_real_desk_wrappers(handler, "expanded_top_with_anchor.xml")
    assert len(desks) >= 1

    # 第一张桌位：根据真实 dump 判定
    reading_left = reader.read(desks[0], "left")
    reading_right = reader.read(desks[0], "right")

    assert isinstance(reading_left, Reading)
    assert isinstance(reading_right, Reading)
    assert not (reading_left.occupied and reading_left.is_empty)
    assert not (reading_right.occupied and reading_right.is_empty)


def test_read_synthetic_desk_occupancy_and_empty():
    """合成 XML 测试：正向证据优先，空座判据明确。"""
    handler = make_handler()
    reader = SeatPanelReader(handler)

    # 1. 占座：有 ClState
    desk_occ = build_desk_wrapper(handler, left="Bob", right="2", left_occupied=True)
    r_left = reader.read(desk_occ, "left")
    r_right = reader.read(desk_occ, "right")
    assert r_left.occupied is True
    assert r_left.is_empty is False
    assert r_left.label == "Bob"

    assert r_right.occupied is False
    assert r_right.is_empty is True
    assert r_right.label == "2"

    # 2. 占座：多头像图（即使没有 ClState）
    desk_multi_img = build_desk_wrapper(
        handler,
        left="1",
        right="2",
        left_occupied=False,
        left_avatar_images=2,
    )
    r_multi = reader.read(desk_multi_img, "left", seat_number=1)
    assert r_multi.occupied is True
    assert r_multi.is_empty is False

    # 3. 空座：数字匹配
    desk_num = build_desk_wrapper(handler, left="7", right="8", left_occupied=False)
    r_7 = reader.read(desk_num, "left", seat_number=7)
    r_wrong_num = reader.read(desk_num, "left", seat_number=5)
    assert r_7.occupied is False
    assert r_7.is_empty is True
    # 数字不匹配时不视为空座（防止串号）
    assert r_wrong_num.is_empty is False

    # 4. 空座：点击入座
    desk_default = build_desk_wrapper(handler, left="点击入座", right="入座", left_occupied=False)
    assert reader.read(desk_default, "left").is_empty is True
    assert reader.read(desk_default, "right").is_empty is True


def test_read_raw_desk_shape():
    """raw WebElement 形状支持。"""
    handler = make_handler()
    reader = SeatPanelReader(handler)

    children = {
        "cn.soulapp.android:id/leftUserView": ClickableNode(""),
        "cn.soulapp.android:id/leftClState": ClickableNode(""),
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("Tom"),
        "cn.soulapp.android:id/rightUserView": ClickableNode(""),
        "cn.soulapp.android:id/rightTvLabelH": ClickableNode("2"),
    }
    raw_desk = RawSeatDesk(children)

    r_left = reader.read(raw_desk, "left")
    r_right = reader.read(raw_desk, "right", seat_number=2)

    assert r_left.occupied is True
    assert r_left.label == "Tom"
    assert r_right.occupied is False
    assert r_right.is_empty is True
    assert r_right.label == "2"


@pytest.mark.asyncio
async def test_session_reentrant_and_depth():
    """验证 ui_session 可重入与 reader 自身的 depth 追踪。"""
    ctrl = FakeController()
    handler = make_handler(controller=ctrl)
    reader = SeatPanelReader(handler)

    assert reader.holds_session is False
    assert reader.busy_elsewhere is False
    assert reader.can_probe_ui is True

    async with reader.session("outer") as held1:
        assert held1 is True
        assert reader.holds_session is True
        assert reader.busy_elsewhere is False
        assert reader.can_probe_ui is True

        # 同 task 嵌套进入
        async with reader.session("inner") as held2:
            assert held2 is True
            assert reader.holds_session is True
            assert len(ctrl.sessions) == 1  # 真实锁只申请了一次

        assert reader.holds_session is True

    assert reader.holds_session is False
    assert len(ctrl.sessions) == 1


@pytest.mark.asyncio
async def test_session_skip_if_busy():
    """验证 skip_if_busy=True 时被占用直出 False，空闲时成功持锁。"""
    ctrl = FakeController()
    handler = make_handler(controller=ctrl)
    reader = SeatPanelReader(handler)

    # 1. 空闲时
    async with reader.session("free_task", skip_if_busy=True) as held:
        assert held is True
        assert reader.holds_session is True

    # 2. 外部任务持锁时
    async def other_holder(barrier_acquired, barrier_release):
        async with ctrl.ui_session("other_blocker"):
            barrier_acquired.set()
            await barrier_release.wait()

    acquired = asyncio.Event()
    release = asyncio.Event()
    task = asyncio.create_task(other_holder(acquired, release))
    await acquired.wait()

    try:
        assert reader.holds_session is False
        assert reader.busy_elsewhere is True
        assert reader.can_probe_ui is False

        # 尝试 skip_if_busy 进入
        async with reader.session("probe", skip_if_busy=True) as held:
            assert held is False
            assert reader.holds_session is False

        # 验证此时并未获取锁
        assert "probe" not in ctrl.sessions
    finally:
        release.set()
        await task

    # 外部释放后
    assert reader.busy_elsewhere is False
    assert reader.can_probe_ui is True


# ===========================================================================
# 规范 s2 (Issue #488) 要求的契约与不变量测试
# ===========================================================================


def test_spec_tap_geometry_pinning():
    """规范明确要求钉住的几何测试：
    (x, y, width, height) = (100, 200, 400, 300) -> left (200, 350), right (400, 350)。
    """
    reader = SeatPanelReader()
    desk = SimpleNamespace(bounds={"x": 100, "y": 200, "width": 400, "height": 300})
    assert reader.tap_point(desk, "left") == (200, 350)
    assert reader.tap_point(desk, "right") == (400, 350)

    # bounds missing/zero returns None
    assert reader.tap_point(SimpleNamespace(bounds={"x": 100, "y": 200, "width": 0, "height": 300}), "left") is None
    assert reader.tap_point(SimpleNamespace(bounds={"x": 100, "y": 200, "width": 400, "height": 0}), "right") is None
    assert reader.tap_point(SimpleNamespace(bounds=None), "left") is None
    assert reader.tap_point(SimpleNamespace(), "left") is None


def test_positive_evidence_signals_individual():
    """验证每个正向证据都能独立判定 occupied = True：
    1. ClState
    2. RankView
    3. avatar_images > 1
    4. non-numeric / non-empty label
    """
    handler = make_handler()
    reader = SeatPanelReader(handler)

    # 1. ClState
    raw_cl_state = RawSeatDesk({
        "cn.soulapp.android:id/leftClState": ClickableNode(""),
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("1"),  # 即使标签是座位号
    })
    r_state = reader.read(raw_cl_state, "left", seat_number=1)
    assert r_state.occupied is True
    assert r_state.is_empty is False

    # 2. RankView
    raw_rank = RawSeatDesk({
        "cn.soulapp.android:id/leftRankView": ClickableNode(""),
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("1"),  # 即使标签是座位号
    })
    r_rank = reader.read(raw_rank, "left", seat_number=1)
    assert r_rank.occupied is True
    assert r_rank.is_empty is False

    # 3. avatar_images > 1 (avatar count = 2)
    desk_avatar2 = build_desk_wrapper(
        handler,
        left="1",
        left_occupied=False,
        left_avatar_images=2,
    )
    r_avatar2 = reader.read(desk_avatar2, "left", seat_number=1)
    assert r_avatar2.occupied is True
    assert r_avatar2.is_empty is False

    # 4. non-numeric label
    raw_nick = RawSeatDesk({
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("SoulMate"),
    })
    r_nick = reader.read(raw_nick, "left")
    assert r_nick.occupied is True
    assert r_nick.is_empty is False


def test_empty_evidence_signals_individual():
    """验证每个空座证据都能判定 empty = True（在无正向证据时）：
    1. TvDefaultName ("点击入座")
    2. placeholder label ("入座")
    3. matching 1-12 seat number
    4. exactly one avatar image
    """
    handler = make_handler()
    reader = SeatPanelReader(handler)

    # 1. TvDefaultName
    raw_default = RawSeatDesk({
        "cn.soulapp.android:id/leftTvDefaultName": ClickableNode("点击入座"),
    })
    r_def = reader.read(raw_default, "left")
    assert r_def.occupied is False
    assert r_def.is_empty is True

    # 2. placeholder label
    raw_ph = RawSeatDesk({
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("入座"),
    })
    r_ph = reader.read(raw_ph, "left")
    assert r_ph.occupied is False
    assert r_ph.is_empty is True

    # 3. matching 1-12 seat number
    raw_num = RawSeatDesk({
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("5"),
    })
    r_num = reader.read(raw_num, "left", seat_number=5)
    assert r_num.occupied is False
    assert r_num.is_empty is True

    # 4. exactly one avatar image (without seat number or text)
    desk_avatar1 = build_desk_wrapper(
        handler,
        left="",
        left_occupied=False,
        left_avatar_images=1,
    )
    r_av1 = reader.read(desk_avatar1, "left")
    assert r_av1.occupied is False
    assert r_av1.is_empty is True


def test_positive_evidence_wins_over_empty_evidence():
    """规范明确要求：正向证据优先（Positive evidence wins）。
    当元素同时具备空座证据（如座位号 3）和正向证据（如 RankView / ClState / 多个头像图），
    必须判定为 occupied=True，is_empty=False。
    """
    handler = make_handler()
    reader = SeatPanelReader(handler)

    # 座位号匹配 (3) + RankView -> occupied=True
    raw_rank_and_seat = RawSeatDesk({
        "cn.soulapp.android:id/leftRankView": ClickableNode(""),
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("3"),
    })
    r1 = reader.read(raw_rank_and_seat, "left", seat_number=3)
    assert r1.occupied is True
    assert r1.is_empty is False

    # TvDefaultName ("点击入座") + ClState -> occupied=True
    raw_def_and_state = RawSeatDesk({
        "cn.soulapp.android:id/leftTvDefaultName": ClickableNode("点击入座"),
        "cn.soulapp.android:id/leftClState": ClickableNode(""),
    })
    r2 = reader.read(raw_def_and_state, "left")
    assert r2.occupied is True
    assert r2.is_empty is False

    # 座位号匹配 (4) + avatar_images=2 -> occupied=True
    desk_av_and_seat = build_desk_wrapper(
        handler,
        left="4",
        left_occupied=False,
        left_avatar_images=2,
    )
    r3 = reader.read(desk_av_and_seat, "left", seat_number=4)
    assert r3.occupied is True
    assert r3.is_empty is False


def test_unreadable_cases_do_not_default_to_empty():
    """规范明确要求：无法辨识（无任何证据）或折叠/裁剪时，不得退化为空座。
    occupied=False, is_empty=False, readable=False。
    """
    handler = make_handler()
    reader = SeatPanelReader(handler)

    # 毫无证据
    raw_empty = RawSeatDesk({})
    r_empty = reader.read(raw_empty, "left")
    assert r_empty.occupied is False
    assert r_empty.is_empty is False
    assert r_empty.readable is False

    # 只有空白 label，无其他节点
    raw_blank = RawSeatDesk({
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("   "),
    })
    r_blank = reader.read(raw_blank, "left")
    assert r_blank.occupied is False
    assert r_blank.is_empty is False
    assert r_blank.readable is False

    # 座位号不匹配（label='8', seat_number=3）
    raw_mismatch = RawSeatDesk({
        "cn.soulapp.android:id/leftTvLabelH": ClickableNode("8"),
    })
    r_mismatch = reader.read(raw_mismatch, "left", seat_number=3)
    assert r_mismatch.occupied is False
    assert r_mismatch.is_empty is False
    assert r_mismatch.readable is False


def test_composition_root_wires_panel_reader():
    """组合根接线测试：SeatObservationManager.initialize 接收并持有来自 SeatSubsystem 的 panel_reader。"""
    from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
    from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

    handler = make_handler(controller=FakeController())
    subsystem = SeatSubsystem(handler)
    reader = subsystem.panel_reader
    assert isinstance(reader, SeatPanelReader)
    assert subsystem.panel_driver.panel_reader is reader

    SeatObservationManager.reset_instance()
    try:
        observation = SeatObservationManager.initialize(handler, panel_reader=reader)
        assert observation.panel_reader is reader
    finally:
        SeatObservationManager.reset_instance()


@pytest.mark.asyncio
async def test_prepare_for_chat_scan_when_busy_elsewhere():
    """prepare_for_chat_scan 查验 UI 独占：外部任务持有时，退出并保持面板不动。"""
    from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

    ctrl = FakeController()
    handler = make_handler(controller=ctrl)
    subsystem = SeatSubsystem(handler)

    class DummyPanel:
        def __init__(self):
            self.collapsed = False
        def check_seats_state(self):
            return True
        async def collapse_seats(self):
            self.collapsed = True
            return True

    panel = DummyPanel()
    subsystem._panel = panel

    # 外部任务持有 controller.ui_session
    async with ctrl.ui_session("other_worker"):
        assert subsystem.panel_reader.busy_elsewhere is True
        res = await subsystem.prepare_for_chat_scan()
        assert res is True
        # 面板保持原状，未收起
        assert panel.collapsed is False


def test_semantic_consistency_across_subsystem_and_observation():
    """语义一致性：对于同一张 desk，SeatPanelReader、SeatObservationManager
    与 SeatSubsystem 的判定完全一致。
    """
    from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
    from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

    handler = make_handler(controller=FakeController())
    subsystem = SeatSubsystem(handler)
    SeatObservationManager.reset_instance()
    try:
        observation = SeatObservationManager.initialize(handler, panel_reader=subsystem.panel_reader)

        # 占座桌：有 RankView + 多头像
        desk_occ = build_desk_wrapper(handler, left="1", right="2", left_occupied=False, left_avatar_images=2)
        r_occ = subsystem.panel_reader.read(desk_occ, "left", seat_number=1)
        assert r_occ.occupied is True
        assert r_occ.is_empty is False

        info = observation._extract_seat_info(desk_occ, "left", seat_num=1)
        assert info["occupied"] is True
        assert info["is_empty"] is False

        d_info = subsystem._collect_desk_info(desk_occ)
        assert d_info["left"]["occupied"] is True
        assert d_info["left"]["label"] == "1"
    finally:
        SeatObservationManager.reset_instance()


def test_ast_invariants():
    """AST 与代码文本静态不变量测试：
    1. src/ 下没有任何 'caller_holds_ui_session'；
    2. subsystem.py 中没有任何 'bool(left_state)' 或 'bool(right_state)'；
    3. seat_manager 中除 seat_panel_reader.py 外，没有直接调用 controller.ui_session；
    4. seat_observation.py, seat_panel_driver.py, subsystem.py 中没有任何 '// 4' 座位点击公式；
    5. SeatObservationManager 已删除 read_seat_occupancy, seat_click_position, is_ui_busy；
       SeatSubsystem 已删除 _ui_is_busy。
    """
    import ast
    from pathlib import Path
    from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
    from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"

    # 1. src/ 下没有任何 caller_holds_ui_session
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "caller_holds_ui_session" not in content, f"{py_file} still references caller_holds_ui_session"

    # 2. subsystem.py 中没有任何 bool(left_state) 或 bool(right_state)
    subsystem_content = (src_dir / "ushareiplay/managers/seat_manager/subsystem.py").read_text(encoding="utf-8")
    assert "bool(left_state)" not in subsystem_content
    assert "bool(right_state)" not in subsystem_content

    # 3. seat_manager 中除 seat_panel_reader.py 外，没有任何地方直接调用 controller.ui_session
    seat_mgr_dir = src_dir / "ushareiplay/managers/seat_manager"
    for py_file in seat_mgr_dir.glob("*.py"):
        if py_file.name == "seat_panel_reader.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # 检查直接通过 controller 调用 ui_session
                if isinstance(func, ast.Attribute) and func.attr == "ui_session":
                    # 只允许调用 panel_reader.session
                    assert not (isinstance(func.value, ast.Attribute) and func.value.attr == "controller"), (
                        f"{py_file.name} directly calls controller.ui_session"
                    )

    # 4. seat_observation, seat_panel_driver, subsystem 中没有 '// 4' 坐标计算 (x + width // 4)
    for name in ("seat_observation.py", "seat_panel_driver.py", "subsystem.py"):
        tree = ast.parse((seat_mgr_dir / name).read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.FloorDiv):
                if isinstance(node.right, ast.Constant) and node.right.value == 4:
                    raise AssertionError(f"{name} contains '// 4' tap coordinate calculation")

    # 5. 已退役的方法必须在类上消失
    assert not hasattr(SeatObservationManager, "read_seat_occupancy")
    assert not hasattr(SeatObservationManager, "seat_click_position")
    assert not hasattr(SeatObservationManager, "is_ui_busy")
    assert not hasattr(SeatSubsystem, "_ui_is_busy")

