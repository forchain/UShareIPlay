"""专注人数必须随时可读 —— 「未知」会让唯一的对账依据整个失效。

背景（真机 10-10 01:49:30~01:50:32）：日志连打 4~5 遍扫描却零次座位更新，
每一行都写着「专注人数: 未知」。人数只有一个来源 —— FocusCountEvent 在**人数
变化时**被动写缓存；冷启动进房 / RoomState.clear() 之后 / 人数没变而 seat 事件
先到，缓存就是空的。tvStudyRoomDesc 明明一直写着「7人专注中」。

「未知」不是显示问题：`_verify_focus_consistency` 拿到 None 就整段 return，
一次账都没对过，错的快照被当成对的留下来。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.seat_fixtures import FakeSeatUI, make_handler
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def _reset():
    SeatObservationManager.reset_instance()
    RoomState.reset_instance()
    RoomState.initialize()  # 组合根在生产里一定会建；事件链路的两个缓存都写它
    yield
    SeatObservationManager.reset_instance()
    RoomState.reset_instance()


def _focus_node(text):
    """界面上真实存在的 tvStudyRoomDesc 节点。"""
    return SimpleNamespace(text=text)


def _with_live_focus(handler, text):
    """让 element_finder 能按需读到专注人数（生产上就是 try_find_element）。"""
    handler.element_finder.try_find_element = lambda key, **kwargs: (
        _focus_node(text) if key == "focus_count" else None
    )
    return handler


def _full_scan(occupied=(9, 10, 11, 12)):
    """一轮读满了 12 个号位、在座数可数的全量重扫结果。"""
    return {
        num: (
            None,
            "left",
            {
                "occupied": num in occupied,
                "is_empty": num not in occupied,
                "username": None,
            },
        )
        for num in range(1, 13)
    }


class TestOnDemandFocusCountRead:
    """修复点 1：观测器能按需读界面上的专注人数。"""

    def test_reads_focus_count_from_ui_element(self):
        handler = _with_live_focus(make_handler(), "7人专注中")
        manager = SeatObservationManager.initialize(handler)

        assert manager.read_focus_count_from_ui() == 7

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("7人专注中", 7),
            ("12人专注中", 12),
            ("1人专注中", 1),
            ("3", 3),  # 兜底：文案变形时仍取数字
            ("", None),
            (None, None),
        ],
    )
    def test_parses_focus_count_text(self, text, expected):
        handler = _with_live_focus(make_handler(), text)
        manager = SeatObservationManager.initialize(handler)

        assert manager.read_focus_count_from_ui() == expected

    def test_returns_none_when_element_absent(self):
        """元素读不到时返回 None（不抛、不假装有值）。"""
        handler = make_handler()
        handler.element_finder.try_find_element = lambda key, **kwargs: None
        manager = SeatObservationManager.initialize(handler)

        assert manager.read_focus_count_from_ui() is None

    def test_returns_none_when_finder_lacks_the_api(self):
        """finder 整个缺席时不能炸（降级环境：观测器可能没有 element_finder）。"""
        handler = make_handler()
        handler.element_finder = None
        manager = SeatObservationManager.initialize(handler)

        assert manager.read_focus_count_from_ui() is None

    def test_driver_failure_does_not_propagate(self):
        """driver 抛错时对账降级为「未知」，而不是把扫描整轮带崩。"""
        handler = make_handler()

        def _boom(key, **kwargs):
            raise RuntimeError("driver gone")

        handler.element_finder.try_find_element = _boom
        manager = SeatObservationManager.initialize(handler)

        assert manager.read_focus_count_from_ui() is None


class TestRescanReconcilesAgainstLiveCount:
    """修复点 2：重扫拿到 None 时按界面补读，让自检真正跑起来。"""

    @pytest.mark.asyncio
    async def test_rescan_reports_the_live_count_instead_of_unknown(self):
        handler = _with_live_focus(make_handler(), "7人专注中")
        manager = SeatObservationManager.initialize(handler)
        manager._seat_ui = FakeSeatUI(desks=[SimpleNamespace()])
        manager._last_focus_count = None

        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            with patch.object(
                manager, "_scan_all_rows_expanded", new=AsyncMock(return_value=_full_scan())
            ):
                await manager.expand_rescan_and_collapse(None)

        logged = "".join(str(c) for c in handler.logger.info.call_args_list)
        assert "专注人数: 7" in logged
        assert "专注人数: 未知" not in logged

    @pytest.mark.asyncio
    async def test_rescan_reconciles_seated_count_against_live_count(self):
        """核心回归：读出 4 个在座、界面写 7 人时，必须挂起重扫并告警。

        修复前 target=None → `_verify_focus_consistency` 直接 return，
        一次账都没对，错的快照被当成对的。
        """
        handler = _with_live_focus(make_handler(), "7人专注中")
        manager = SeatObservationManager.initialize(handler)
        manager._seat_ui = FakeSeatUI(desks=[SimpleNamespace()])
        manager._last_focus_count = None

        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            with patch.object(
                manager, "_scan_all_rows_expanded", new=AsyncMock(return_value=_full_scan())
            ):
                await manager.expand_rescan_and_collapse(None)

        warnings = [str(c) for c in handler.logger.warning.call_args_list]
        assert any("not self-consistent" in w for w in warnings), warnings
        assert manager._consistency_retry_due is True

    @pytest.mark.asyncio
    async def test_rescan_agrees_when_counts_match(self):
        """读数与人数一致时不误报。"""
        handler = _with_live_focus(make_handler(), "4人专注中")
        manager = SeatObservationManager.initialize(handler)
        manager._seat_ui = FakeSeatUI(desks=[SimpleNamespace()])
        manager._last_focus_count = None

        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            with patch.object(
                manager, "_scan_all_rows_expanded", new=AsyncMock(return_value=_full_scan())
            ):
                await manager.expand_rescan_and_collapse(None)

        warnings = [str(c) for c in handler.logger.warning.call_args_list]
        assert not any("not self-consistent" in w for w in warnings), warnings
        assert manager._consistency_retry_due is False

    @pytest.mark.asyncio
    async def test_explicit_target_wins_over_live_read(self):
        """调用方给了人数就用它，不去多读一次界面。"""
        handler = _with_live_focus(make_handler(), "7人专注中")
        manager = SeatObservationManager.initialize(handler)
        manager._seat_ui = FakeSeatUI(desks=[SimpleNamespace()])

        calls = []
        real_read = manager.read_focus_count_from_ui

        def _tracked():
            calls.append(1)
            return real_read()

        manager.read_focus_count_from_ui = _tracked

        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            with patch.object(
                manager, "_scan_all_rows_expanded", new=AsyncMock(return_value=_full_scan())
            ):
                await manager.expand_rescan_and_collapse(4)

        assert calls == [], "已有 target 时不该再读界面"
        assert manager._last_focus_count == 4

    @pytest.mark.asyncio
    async def test_unreadable_count_stays_unknown_but_scan_still_lands(self):
        """界面上真的读不到时保持「未知」，但扫描本身仍然落地。"""
        handler = make_handler()
        handler.element_finder.try_find_element = lambda key, **kwargs: None
        manager = SeatObservationManager.initialize(handler)
        manager._seat_ui = FakeSeatUI(desks=[SimpleNamespace()])

        with patch("ushareiplay.managers.command_manager.CommandManager.instance") as cmd_mgr:
            cmd_mgr.return_value.notify_focus_count_change = AsyncMock()
            with patch.object(
                manager, "_scan_all_rows_expanded", new=AsyncMock(return_value=_full_scan())
            ):
                changed = await manager.expand_rescan_and_collapse(None)

        assert changed is True
        assert manager._last_rescan_ok is True
        logged = "".join(str(c) for c in handler.logger.info.call_args_list)
        assert "专注人数: 未知" in logged


class TestFocusCountEventSeedsCache:
    """修复点 3：事件链路首轮就把人数写进缓存，不再靠「变化」才写。"""

    @pytest.mark.asyncio
    async def test_seat_desk_path_receives_live_count_when_cache_is_empty(self):
        """冷启动首轮：缓存空，但界面可读 → 座位观测拿到真实人数，不是 None。"""
        from ushareiplay.events.focus_count import FocusCountEvent

        handler = _with_live_focus(make_handler(), "7人专注中")
        observation = SeatObservationManager.initialize(handler)
        observation.observe_visible_desks = AsyncMock()

        event = FocusCountEvent(handler=handler)
        assert event.previous_focus_count is None

        await event.handle("seat_desk", [SimpleNamespace(), SimpleNamespace()])

        kwargs = observation.observe_visible_desks.await_args.kwargs
        assert kwargs["current_focus_count"] == 7

    @pytest.mark.asyncio
    async def test_seat_desk_path_does_not_read_ui_when_cache_is_warm(self):
        """缓存已有值时不额外读界面（避免每轮轮询都打 driver）。"""
        from ushareiplay.events.focus_count import FocusCountEvent

        handler = _with_live_focus(make_handler(), "7人专注中")
        observation = SeatObservationManager.initialize(handler)
        observation.observe_visible_desks = AsyncMock()

        event = FocusCountEvent(handler=handler)
        event.previous_focus_count = 5

        reads = []
        handler.element_finder.try_find_element = lambda key, **kwargs: (
            reads.append(key) or _focus_node("7人专注中")
        )

        await event.handle("seat_desk", [SimpleNamespace()])

        assert reads == []
        assert observation.observe_visible_desks.await_args.kwargs["current_focus_count"] == 5

    @pytest.mark.asyncio
    async def test_seat_desk_cold_read_is_cached_and_happens_once(self):
        """冷读只发生一次：读到就写回缓存，不能每轮轮询都打 driver。

        AGENTS.md 日志铁律：无行为触发的监控轮询不得反复产生 UI 动作。
        """
        from ushareiplay.events.focus_count import FocusCountEvent

        handler = _with_live_focus(make_handler(), "7人专注中")
        observation = SeatObservationManager.initialize(handler)
        observation.observe_visible_desks = AsyncMock()

        reads = []
        handler.element_finder.try_find_element = lambda key, **kwargs: (
            reads.append(key) or _focus_node("7人专注中")
        )

        event = FocusCountEvent(handler=handler)
        assert event.previous_focus_count is None

        for _ in range(5):
            await event.handle("seat_desk", [SimpleNamespace()])

        assert reads == ["focus_count"], f"冷读只应发生一次，实际 {reads}"
        assert event.previous_focus_count == 7

    @pytest.mark.asyncio
    async def test_seat_desk_does_not_re_read_when_ui_read_fails(self):
        """界面读不到时也不该每轮重试到把 driver 打爆：一次失败后走缓存(None)路径。

        这里允许继续尝试（元素可能只是这一帧没渲染出来），但必须每次都是
        try_find_element 返回 None 的降级，不抛错、不写脏值。
        """
        from ushareiplay.events.focus_count import FocusCountEvent

        handler = make_handler()
        handler.element_finder.try_find_element = lambda key, **kwargs: None
        observation = SeatObservationManager.initialize(handler)
        observation.observe_visible_desks = AsyncMock()

        event = FocusCountEvent(handler=handler)

        for _ in range(3):
            await event.handle("seat_desk", [SimpleNamespace()])

        assert event.previous_focus_count is None
        assert observation.observe_visible_desks.await_count == 3

    @pytest.mark.asyncio
    async def test_first_focus_count_event_seeds_cache_even_without_change(self):
        """人数与 RoomState 都空时，首次事件也必须把值写进去。"""
        from ushareiplay.events.focus_count import FocusCountEvent
        from ushareiplay.state.room_state import RoomState

        handler = make_handler()
        observation = SeatObservationManager.initialize(handler)
        observation.on_focus_count = AsyncMock()

        RoomState.reset_instance()
        room_state = RoomState.initialize()
        assert room_state.focus_count is None

        event = FocusCountEvent(handler=handler)
        assert event.previous_focus_count is None

        await event.handle("focus_count", SimpleNamespace(text="7人专注中"))

        assert room_state.focus_count == 7
        assert event.previous_focus_count == 7

    @pytest.mark.asyncio
    async def test_unchanged_count_still_seeds_a_cleared_room_state(self):
        """人数没变但 RoomState 被 clear() 过 → 仍然要补写，否则「未知」复发。"""
        from ushareiplay.events.focus_count import FocusCountEvent
        from ushareiplay.state.room_state import RoomState

        handler = make_handler()
        observation = SeatObservationManager.initialize(handler)
        observation.on_focus_count = AsyncMock()

        RoomState.reset_instance()
        room_state = RoomState.initialize()

        event = FocusCountEvent(handler=handler)
        event.previous_focus_count = 7

        await event.handle("focus_count", SimpleNamespace(text="7人专注中"))

        assert room_state.focus_count == 7
