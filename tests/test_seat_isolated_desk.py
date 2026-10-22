"""独立空桌（社恐模式）的选取与真机核验。

「独立空桌」= 同一张桌子的左右两个座位都没有人在座。房里 6 张桌子对应 1~12 号
座位：桌号 0..5 ↔ 座位 (1,2) (3,4) (5,6) (7,8) (9,10) (11,12)。只要一侧有人，
这张桌就不算独立（社恐排除）。

候选桌来自 `SeatObservationManager` 的缓存座次表（快，但可能滞后），每张候选桌
都要滚进视口、用真机 DOM 证据复核：现场发现有人就换下一张候选桌；现场读不出
证据的位子一律不算「核验通过」——没核验过的空桌不能当成空桌。

DOM 形状全部取自真机 dump 生成的夹具（`tests/seat_fixtures.build_live_page_source`）：
顶相位完整渲染 1~8 号座位（桌 0~3），底相位完整渲染 5~12 号座位（桌 2~5），
另一相位只露出底座残片。视口相位由面板替身随滚动切换，与真机一致。
"""

from unittest.mock import MagicMock

import pytest
from lxml import etree

from tests.seat_fixtures import (
    DESK_RESOURCE_ID,
    build_live_page_source,
    make_handler,
)
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)
from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem
from ushareiplay.managers.seat_manager import SeatManager

# 桌号 -> 左右两个座位号（奇数在左、偶数在右）
DESK_SEATS = {desk: (desk * 2 + 1, desk * 2 + 2) for desk in range(6)}


class FakePhaseDriver:
    """按当前视口相位给 page_source 的 driver 替身。

    真机上滚到哪一排决定这一屏能读到哪些座位：顶相位看得见 1~8 号座位，底相位
    看得见 5~12 号座位。替身把这条规则做进 page_source，测试才能验证「核验必须
    发生在正确的视口相位上」。
    """

    def __init__(self, sources: dict):
        self.sources = sources
        self.phase = "top"

    @property
    def page_source(self):
        return self.sources[self.phase]


class FakePhaseSeatUI:
    """座位面板替身：滚到哪一排，就把视口切到那一相位。"""

    def __init__(self, driver):
        self.driver = driver
        self.expand_calls = 0
        self.scroll_calls = []

    async def expand_and_find_desks(self):
        self.expand_calls += 1
        return [MagicMock() for _ in range(6)]

    async def collapse_seats(self):
        return True

    def scroll_to_row(self, desk_index, seat_desks=None, duration=100):
        self.scroll_calls.append(desk_index)
        # 第三排（桌 4/5）必须滚到底部相位；第一、二排在顶相位视口内。
        self.driver.phase = "bottom" if desk_index >= 4 else "top"


def _strip_left_seat_evidence(page_source: str, desk_index: int) -> str:
    """把某张桌的左座渲染成「什么都没有」：userView 在，但里面一个节点都没有。

    这是真机上「读不出判据」的形状：既没有占座证据（ClState / 头像 / 编号），
    也没有空座证据（占位图 / 「点击入座」）。它既不是占座，也不是空座 ——
    没核验过的桌位不能当成空桌。
    """
    root = etree.fromstring(page_source.encode("utf-8"))
    desks = root.xpath(f"//*[@resource-id='{DESK_RESOURCE_ID}']")
    desk = desks[desk_index]
    for node in desk.xpath(".//*[contains(@resource-id, 'leftUserView')]"):
        for child in list(node):
            node.remove(child)
    return etree.tostring(root, encoding="unicode")


def _make_subsystem(cached_occupied=(), live_occupants=None, top_source=None):
    """搭一套子系统：缓存座次表 + 现场 DOM（顶/底两个相位）。"""
    handler = make_handler()
    live = dict(live_occupants or {})
    driver = FakePhaseDriver(
        {
            "top": top_source
            if top_source is not None
            else build_live_page_source(live, "top"),
            "bottom": build_live_page_source(live, "bottom"),
        }
    )
    handler.driver = driver

    observation = SeatObservationManager.initialize(handler)
    for seat in cached_occupied:
        observation.seats[seat] = SeatSlot(
            seat_number=seat, occupied=True, username="Someone", label=str(seat)
        )

    seat_ui = FakePhaseSeatUI(driver)
    subsystem = SeatSubsystem(handler=handler, seat_ui=seat_ui, observation=observation)
    return subsystem, observation, seat_ui


def _info_logs(subsystem):
    return [call.args[0] for call in subsystem.logger.info.call_args_list if call.args]


@pytest.fixture(autouse=True)
def reset_observation():
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()
    SeatManager.reset_instance()


@pytest.fixture(autouse=True)
def no_settle_wait(monkeypatch):
    """滚动后的安定等待在测试里去掉（它是墙钟时间，不是行为）。"""
    monkeypatch.setattr(SeatSubsystem, "VIEWPORT_SETTLE_SECONDS", 0)


# ---------------------------------------------------------------------------
# 选得出来的情况
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_seats_empty_returns_a_verified_desk():
    """全场空座：第一张候选桌核验通过，返回它的推荐空座。"""
    subsystem, observation, seat_ui = _make_subsystem()

    result = await subsystem.find_verified_isolated_empty_desk()

    assert result is not None
    desk_index, seat_number = result
    assert desk_index == 0, "候选按桌号 0..5 依次核验，第一张就是 0 号桌"
    assert seat_number == DESK_SEATS[desk_index][0], "推荐的是这张桌的左座（奇数号）"
    assert seat_ui.expand_calls == 1


@pytest.mark.asyncio
async def test_half_full_room_returns_a_desk_with_two_empty_seats():
    """半空场：返回的那张桌，左右两座都真的没人。"""
    live = {1: True, 3: True}
    subsystem, observation, seat_ui = _make_subsystem(
        cached_occupied={1, 3}, live_occupants=live
    )

    result = await subsystem.find_verified_isolated_empty_desk()

    assert result is not None
    desk_index, seat_number = result
    left, right = DESK_SEATS[desk_index]
    assert live.get(left) is None and live.get(right) is None
    assert seat_number in (left, right)


@pytest.mark.asyncio
async def test_desk_with_an_occupied_neighbour_is_never_selected():
    """一张桌只要有一侧有人，就不算独立空桌（社恐排除）。"""
    live = {2: True}  # 1 号桌的右座有人
    subsystem, observation, seat_ui = _make_subsystem(
        cached_occupied={2}, live_occupants=live
    )

    result = await subsystem.find_verified_isolated_empty_desk()

    assert result is not None
    desk_index, seat_number = result
    assert desk_index != 0, "1 号桌有人陪坐，不能算独立空桌"
    left, right = DESK_SEATS[desk_index]
    assert live.get(left) is None and live.get(right) is None


@pytest.mark.asyncio
async def test_desk_in_the_third_row_is_found_through_the_bottom_viewport():
    """第三排（9~12 号座位）的候选桌要靠底相位视口才读得到。"""
    live = {1: True, 3: True, 5: True, 7: True}
    subsystem, observation, seat_ui = _make_subsystem(
        cached_occupied={1, 3, 5, 7}, live_occupants=live
    )

    result = await subsystem.find_verified_isolated_empty_desk()

    assert result == (4, 9)
    assert 4 in seat_ui.scroll_calls, "第三排的桌要滚到底部相位"


@pytest.mark.asyncio
async def test_result_is_a_two_tuple_of_desk_index_and_seat_number():
    """返回值形状：2 元组（桌号, 推荐空座号）。"""
    subsystem, observation, seat_ui = _make_subsystem()

    result = await subsystem.find_verified_isolated_empty_desk()

    assert isinstance(result, tuple)
    assert len(result) == 2
    desk_index, seat_number = result
    assert isinstance(desk_index, int) and 0 <= desk_index <= 5
    assert isinstance(seat_number, int) and 1 <= seat_number <= 12
    assert seat_number in DESK_SEATS[desk_index]


# ---------------------------------------------------------------------------
# 缓存滞后与读不出证据
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_cache_skips_the_desk_that_is_now_occupied():
    """缓存说 1 号桌空，现场有人：跳过它，核验下一张候选桌。"""
    live = {1: True}
    subsystem, observation, seat_ui = _make_subsystem(live_occupants=live)

    result = await subsystem.find_verified_isolated_empty_desk()

    assert result == (1, 3), "缓存滞后的桌要被跳过，下一张候选桌才该被选中"
    assert any("过期" in message for message in _info_logs(subsystem)), (
        "缓存与现场不一致是一次真实的状态变化，必须报出来"
    )


@pytest.mark.asyncio
async def test_desk_without_dom_evidence_is_not_accepted():
    """现场读不出任何证据的座位不算空座（没核验过 ≠ 空）。"""
    top = _strip_left_seat_evidence(build_live_page_source({}, "top"), 0)
    subsystem, observation, seat_ui = _make_subsystem(top_source=top)

    result = await subsystem.find_verified_isolated_empty_desk()

    assert result == (1, 3), "读不出判据的桌位不能当成独立空桌"


@pytest.mark.asyncio
async def test_all_candidates_failing_verification_returns_none():
    """每张候选桌现场都有人：返回空结果。"""
    live = {1: True, 3: True, 5: True, 7: True, 9: True, 11: True}
    subsystem, observation, seat_ui = _make_subsystem(live_occupants=live)

    assert await subsystem.find_verified_isolated_empty_desk() is None


# ---------------------------------------------------------------------------
# 接线：门面这一层不重复实现逻辑
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_method_is_reachable_through_the_seat_manager_facade():
    """门面不另写一份实现：`SeatManager.subsystem` 上就是同一个方法。

    门面上带客房守卫的包装方法由集成者补齐（#454 与 #455 并行改同一文件），
    这里只钉住「接线层拿得到这个能力」这一条。
    """
    manager = SeatManager.initialize(handler=make_handler())

    assert callable(manager.subsystem.find_verified_isolated_empty_desk)


# ---------------------------------------------------------------------------
# 没有可用独立空桌
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_room_has_no_isolated_empty_desk():
    """全场满座：没有候选桌，直接返回空结果（不动面板）。"""
    subsystem, observation, seat_ui = _make_subsystem(cached_occupied=range(1, 13))

    assert await subsystem.find_verified_isolated_empty_desk() is None
    assert seat_ui.expand_calls == 0, "没有候选桌时不该展开面板"


@pytest.mark.asyncio
async def test_every_desk_has_an_occupied_neighbour_has_no_isolated_empty_desk():
    """每张桌子都有一侧有人：没有独立空桌可挑。"""
    subsystem, observation, seat_ui = _make_subsystem(
        cached_occupied={1, 3, 5, 7, 9, 11}
    )

    assert await subsystem.find_verified_isolated_empty_desk() is None
    assert seat_ui.expand_calls == 0


@pytest.mark.asyncio
async def test_no_isolated_desk_is_reported_once():
    """核验全败时只报一次「没有独立空桌」，不刷屏。"""
    live = {1: True, 3: True, 5: True, 7: True, 9: True, 11: True}
    subsystem, observation, seat_ui = _make_subsystem(live_occupants=live)

    assert await subsystem.find_verified_isolated_empty_desk() is None

    outcomes = [m for m in _info_logs(subsystem) if "独立空桌" in m]
    assert len(outcomes) == 1, f"「没有独立空桌」应该只报一次，实报 {len(outcomes)} 次"


@pytest.mark.asyncio
async def test_no_candidate_desk_is_not_logged():
    """没有候选桌是正常的查询结果，不该刷日志。"""
    subsystem, observation, seat_ui = _make_subsystem(
        cached_occupied={1, 3, 5, 7, 9, 11}
    )

    assert await subsystem.find_verified_isolated_empty_desk() is None

    assert not [m for m in _info_logs(subsystem) if "独立空桌" in m]
