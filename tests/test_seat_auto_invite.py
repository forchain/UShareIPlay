"""进房/回房时没有座位预约 → 自动邀请入座一张独立空桌（社恐模式，票 #455）。

新分支挂在 `SeatSubsystem.check_seats_on_entry` 上：

1. 没有有效预约（压根没有预约，或预约已过期）→ 走社恐模式；
2. 把 canonical 名（主账号名）解析成 Soul UI 上的**可见昵称**（分身名）—— 邀请
   弹窗只认可见昵称；
3. 已经在座的人不打扰；
4. 挑一张左右两座都空的独立桌，并用真机 DOM 证据核验；
5. 点开空座、在弹窗里找到这个人、点「邀请」。

本文件钉得最死的一条是**锁的纪律**：整条链（挑桌 + 邀请）在**同一把** UI 锁下跑完。
`AppController.ui_session` 是可重入的（同一个 task 嵌套进入时直通），所以
`invite_user_to_seat` 自己那层锁在这里不会自锁死；两步之间也不会把锁放出去 ——
那一段窗口里别的 UI 事件（麦位扫描、兜底 back）可能插进来。
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.seat_fixtures import (
    ClickableNode,
    FakeController,
    FakeSeatDesk,
    FakeSeatObservation,
    make_handler,
)
from tests.test_seat_invite_driver import InviteRow, make_invite_handler

from ushareiplay.managers.seat_manager import subsystem as seat_subsystem_module
from ushareiplay.managers.seat_manager.seat_observation import SeatSlot
from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem

# 同一个人的两个命名域：DB 侧是 canonical 名（主账号名），Soul UI 上是可见昵称。
CANONICAL = "alice_master"
VISIBLE = "Alice分身"

DESK_INDEX = 1
DESK_SEAT = 3  # 1 号桌的左座


# ---------------------------------------------------------------------------
# 局部替身
# ---------------------------------------------------------------------------
class FakeIdentityDAO:
    """`UserDAO.is_same_identity` 的替身：按身份组判定同名不同串。"""

    def __init__(self, groups=()):
        self.groups = [set(group) for group in groups]

    async def is_same_identity(self, requested_username, observed_username):
        if not requested_username or not observed_username:
            return False
        if requested_username == observed_username:
            return True
        return any(
            requested_username in group and observed_username in group
            for group in self.groups
        )


class FakeReservationDAO:
    """座位预约 DAO 的替身（只保留进房检查用到的那几个动作）。"""

    def __init__(self, reservation=None):
        self.reservation = reservation
        self.removed = []
        self.renewed = []

    async def get_reservation_by_user_name(self, username):
        return self.reservation

    async def remove_reservation(self, reservation):
        self.removed.append(reservation)

    async def update_reservation_start_time(self, reservation_id, now):
        self.renewed.append((reservation_id, now))


class FakeInfoManager:
    """`InfoManager` 的替身：把 canonical 名解析成房间里可见的昵称。"""

    def __init__(self, visible_by_canonical=None):
        self.visible_by_canonical = visible_by_canonical or {}
        self.resolved = []

    def instance(self):
        return self

    async def resolve_visible_username(self, username):
        self.resolved.append(username)
        return self.visible_by_canonical.get(username, username)


class RecordingSeatUI:
    """面板替身：记录展开/收起/滚动的次数（用来证明「没动过面板」）。"""

    def __init__(self, desks=None):
        self.desks = desks if desks is not None else []
        self.expand_calls = 0
        self.collapse_calls = 0
        self.collapsed = False
        self.scrolled = []

    async def expand_and_find_desks(self):
        self.expand_calls += 1
        return self.desks

    async def collapse_seats(self):
        self.collapse_calls += 1
        self.collapsed = True
        return True

    def scroll_to_row(self, desk_index, seat_desks=None, duration=100):
        self.scrolled.append(desk_index)
        return True


class DeskSearchStub:
    """`find_verified_isolated_empty_desk` 的替身：只回报「挑到了哪张桌」。"""

    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.kwargs = []

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        return self.result


class InviteStub:
    """`invite_user_to_seat` 的替身：记录邀请了谁、哪个座位。"""

    def __init__(self, result=None):
        self.result = result if result is not None else {"success": "已邀请"}
        self.calls = []

    async def __call__(self, seat_number, target_visible_name):
        self.calls.append((seat_number, target_visible_name))
        return self.result


def _reservation(expired=False, seat_number=5):
    """一份预约（过期与否由 expired 决定）。"""
    start = datetime.now() - timedelta(hours=10 if expired else 1)
    return SimpleNamespace(
        id=1,
        seat_number=seat_number,
        start_time=start,
        duration_hours=1 if expired else 5,
        user=SimpleNamespace(username=CANONICAL, level=5),
    )


def _occupied_seats(username, seat_number=5, label="5", is_owner=False):
    """一份「某人已经坐在某号座位上」的缓存座次表。"""
    seats = {number: SeatSlot(seat_number=number) for number in range(1, 13)}
    seats[seat_number] = SeatSlot(
        seat_number=seat_number,
        occupied=True,
        username=username,
        label=label,
        is_owner=is_owner,
    )
    return seats


def _build(
    monkeypatch,
    *,
    reservation=None,
    seats=None,
    desk=(DESK_INDEX, DESK_SEAT),
    invite_result=None,
    stub_desk=True,
    stub_invite=True,
    handler=None,
    controller=None,
    room_owner=None,
):
    """搭一套子系统：DAO / InfoManager / 找桌 / 邀请全部是可控替身。"""
    handler = handler or make_handler(controller=controller or FakeController())
    seat_ui = RecordingSeatUI()
    if seats is None:
        seats = {number: SeatSlot(seat_number=number) for number in range(1, 13)}
    observation = FakeSeatObservation(seats=seats, owner=room_owner)
    subsystem = SeatSubsystem(
        handler=handler, seat_ui=seat_ui, observation=observation
    )

    reservations = FakeReservationDAO(reservation)
    identities = FakeIdentityDAO([(CANONICAL, VISIBLE)])
    info = FakeInfoManager({CANONICAL: VISIBLE})

    monkeypatch.setattr(seat_subsystem_module, "SeatReservationDAO", reservations)
    monkeypatch.setattr(seat_subsystem_module, "UserDAO", identities)
    monkeypatch.setattr(seat_subsystem_module, "InfoManager", info)

    messages = []
    subsystem._message_dispatch = SimpleNamespace(send_screen_message=messages.append)

    desk_search = DeskSearchStub(desk)
    invite = InviteStub(invite_result)
    if stub_desk:
        monkeypatch.setattr(subsystem, "find_verified_isolated_empty_desk", desk_search)
    if stub_invite:
        monkeypatch.setattr(subsystem, "invite_user_to_seat", invite)

    return SimpleNamespace(
        subsystem=subsystem,
        handler=handler,
        seat_ui=seat_ui,
        observation=observation,
        reservations=reservations,
        identities=identities,
        info=info,
        messages=messages,
        desk_search=desk_search,
        invite=invite,
    )


# ---------------------------------------------------------------------------
# 没有预约：自动邀请入座独立空桌
# ---------------------------------------------------------------------------
async def test_entry_without_a_reservation_invites_the_user_to_an_isolated_desk(monkeypatch):
    """没有预约：挑一张独立空桌，用可见昵称把人请过去。"""
    bundle = _build(monkeypatch)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.desk_search.calls == 1, "没有预约就该挑一张独立空桌"
    assert bundle.invite.calls == [(DESK_SEAT, VISIBLE)], (
        "邀请要用桌子的推荐座位号和 UI 上的可见昵称"
    )


async def test_the_invite_uses_the_visible_nickname_and_not_the_canonical_name(monkeypatch):
    """邀请弹窗只认可见昵称：canonical 名绝不能被直接送进去。"""
    bundle = _build(monkeypatch)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.info.resolved == [CANONICAL], "进房用户要先解析成可见昵称"
    seat_number, target = bundle.invite.calls[0]
    assert target == VISIBLE
    assert target != CANONICAL


async def test_a_successful_invite_sends_exactly_one_screen_message(monkeypatch):
    """邀请成功：公屏只说一句，说清是谁、坐哪。"""
    bundle = _build(monkeypatch, invite_result={"success": "已邀请"})

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert len(bundle.messages) == 1
    message = bundle.messages[0]
    assert VISIBLE in message
    assert str(DESK_SEAT) in message


async def test_the_auto_invite_is_reported_at_info_level(monkeypatch):
    """真的发出了邀请：这是一次真实行为，值得记一笔 INFO。"""
    bundle = _build(monkeypatch, invite_result={"success": "已邀请"})

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    info_logs = [
        call.args[0]
        for call in bundle.handler.logger.info.call_args_list
        if call.args
    ]
    assert any(VISIBLE in message for message in info_logs), (
        "发出邀请是真实行为，必须有 INFO 记录"
    )


# ---------------------------------------------------------------------------
# 有有效预约：既有的保座逻辑照走，不做自动邀请
# ---------------------------------------------------------------------------
async def test_a_valid_reservation_keeps_the_hold_seat_path_and_skips_the_auto_invite(monkeypatch):
    """有有效预约：自动续期 + 保座照旧，绝不多事。"""
    reservation = _reservation(expired=False)
    bundle = _build(monkeypatch, reservation=reservation)

    held = []

    async def _hold(username, seat_number):
        held.append((username, seat_number))

    monkeypatch.setattr(bundle.subsystem, "check_user_specific_seat", _hold)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert held == [(CANONICAL, reservation.seat_number)], "有效预约仍走保座逻辑"
    assert bundle.desk_search.calls == 0, "有预约就不该再挑独立空桌"
    assert bundle.invite.calls == [], "有预约就不该发邀请"
    assert bundle.messages == []


async def test_an_expired_reservation_is_removed_and_the_auto_invite_still_happens(monkeypatch):
    """预约过期 = 没有有效预约：清掉过期数据，照样走社恐模式。"""
    reservation = _reservation(expired=True)
    bundle = _build(monkeypatch, reservation=reservation)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.reservations.removed == [reservation], "过期预约要清掉"
    assert bundle.desk_search.calls == 1
    assert bundle.invite.calls == [(DESK_SEAT, VISIBLE)]


# ---------------------------------------------------------------------------
# 已经在座 / 没有独立空桌：什么都不做
# ---------------------------------------------------------------------------
async def test_a_user_who_is_already_seated_is_left_alone(monkeypatch):
    """已经在座：既不挑桌也不发邀请，连公屏都不说。"""
    seats = _occupied_seats(VISIBLE, seat_number=5)
    bundle = _build(monkeypatch, seats=seats)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.desk_search.calls == 0, "已经在座的人不需要新座位"
    assert bundle.invite.calls == []
    assert bundle.messages == []


async def test_the_owner_seat_is_not_mistaken_for_the_entering_user(monkeypatch):
    """群主的座位（label「群主」）不是进房用户的座位。"""
    seats = _occupied_seats(None, seat_number=9, label="群主", is_owner=True)
    bundle = _build(monkeypatch, seats=seats)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.invite.calls == [(DESK_SEAT, VISIBLE)], (
        "群主坐着的那张桌子不算「进房用户已在座」，邀请照发"
    )


async def test_the_room_owner_is_not_pulled_to_another_desk(monkeypatch):
    """房主（群主）本来就有自己的座位：别给他再安排一张空桌。"""
    bundle = _build(monkeypatch, room_owner=CANONICAL)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.desk_search.calls == 0
    assert bundle.invite.calls == []
    assert bundle.messages == []


async def test_a_room_without_an_isolated_empty_desk_leaves_everyone_alone(monkeypatch):
    """全场没有左右两座都空的桌子：静默结束，谁也不打扰。"""
    seats = {
        number: SeatSlot(
            seat_number=number, occupied=True, username=f"user{number}", label=str(number)
        )
        for number in range(1, 13)
    }
    bundle = _build(monkeypatch, seats=seats, stub_desk=False)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.invite.calls == []
    assert bundle.messages == []
    assert bundle.seat_ui.expand_calls == 0, "没有候选桌时连面板都不该展开"
    assert bundle.handler.logger.info.call_args_list == [], (
        "没有动作就不要刷 INFO 日志"
    )


# ---------------------------------------------------------------------------
# 邀请失败：如实记一笔，但不刷屏
# ---------------------------------------------------------------------------
async def test_a_failed_invite_sends_no_screen_message_and_raises_nothing(monkeypatch):
    """用户已经离房（弹窗里找不到）：不公屏报错，异常也不许外泄。"""
    bundle = _build(
        monkeypatch,
        invite_result={"error": f"未在邀请列表中找到 {VISIBLE}"},
    )

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.messages == [], "邀请失败不往公屏上刷"
    assert bundle.handler.logger.info.call_args_list, (
        "邀请失败是一次真实事件，如实记一笔"
    )


# ---------------------------------------------------------------------------
# 锁的纪律
# ---------------------------------------------------------------------------
async def test_the_whole_auto_invite_flow_runs_under_one_ui_session(monkeypatch):
    """找桌 + 邀请全流程在**同一把** UI 锁下跑完。

    `AppController.ui_session` 是可重入的：同一个 task 嵌套进入时直通。所以
    「邀请」那一步自己那层锁不会自锁死，也不会在两步之间把锁放出去 —— 中间那一
    段窗口里，别的 UI 事件（麦位扫描、兜底 back）可能插进来抢座位或关弹窗。

    这里让「邀请」走真实实现：它自己会取一次锁（嵌套）。整条链必须能跑完，
    用超时把「挂住」变成失败。
    """
    controller = FakeController()
    desks = [FakeSeatDesk() for _ in range(6)]
    handler = make_invite_handler(
        pages=[[InviteRow(VISIBLE, "邀请")]], close_button=ClickableNode("")
    )
    handler.controller = controller

    seat_ui = RecordingSeatUI(desks=desks)
    observation = FakeSeatObservation(
        observed={
            DESK_SEAT: (
                desks[1],
                "left",
                {"occupied": False, "is_empty": True},
            )
        }
    )
    subsystem = SeatSubsystem(
        handler=handler, seat_ui=seat_ui, observation=observation
    )

    monkeypatch.setattr(seat_subsystem_module, "InfoManager", FakeInfoManager({CANONICAL: VISIBLE}))
    monkeypatch.setattr(
        seat_subsystem_module, "UserDAO", FakeIdentityDAO([(CANONICAL, VISIBLE)])
    )
    monkeypatch.setattr(
        seat_subsystem_module, "SeatReservationDAO", FakeReservationDAO(None)
    )

    async def _desk_search(*_args, **_kwargs):
        return (DESK_INDEX, DESK_SEAT)

    monkeypatch.setattr(subsystem, "find_verified_isolated_empty_desk", _desk_search)

    messages = []
    subsystem._message_dispatch = SimpleNamespace(send_screen_message=messages.append)

    await asyncio.wait_for(
        subsystem.check_seats_on_entry(CANONICAL), timeout=10
    )

    assert controller.sessions == [f"seat_auto_invite:{CANONICAL}"], (
        "整条链只该申请一次锁：找桌与邀请在同一把锁里"
    )
    assert controller.ui_lock.locked() is False, "锁必须被还回去"
    assert len(messages) == 1, "真实邀请成功后要报一句"


# ---------------------------------------------------------------------------
# 面板必须恢复原状
# ---------------------------------------------------------------------------
async def test_the_panel_is_collapsed_after_the_auto_invite_flow(monkeypatch):
    """#455：退出时面板恢复原状（收起），不能把展开的面板留在房间里。"""
    bundle = _build(monkeypatch)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.seat_ui.collapsed is True, "自动邀请结束后座位面板必须是收起的"


async def test_the_panel_is_collapsed_when_no_isolated_desk_is_found(monkeypatch):
    """没挑到桌也一样要收面板：找桌这一步把面板展开了。"""
    bundle = _build(monkeypatch, desk=None)

    await bundle.subsystem.check_seats_on_entry(CANONICAL)

    assert bundle.seat_ui.collapsed is True, "没挑到桌也不能把展开的面板留在房间里"
    assert bundle.invite.calls == []


# ---------------------------------------------------------------------------
# 客房守卫与既有行为
# ---------------------------------------------------------------------------
async def test_a_guest_room_triggers_no_ui_action_at_all(monkeypatch):
    """他人房间：进房自动邀请整条链路都不许跑。"""
    from ushareiplay.managers.seat_manager import SeatManager
    from ushareiplay.state.room_state import RoomState

    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state.is_guest_room = True

    SeatManager.reset_instance()
    seat_ui = RecordingSeatUI()
    manager = SeatManager.initialize(make_handler(controller=FakeController()), seat_ui=seat_ui)

    def _explode(*_args, **_kwargs):
        raise AssertionError("他人房间里不该跑进房自动邀请的实现")

    monkeypatch.setattr(manager.subsystem, "find_verified_isolated_empty_desk", _explode)
    monkeypatch.setattr(manager.subsystem, "invite_user_to_seat", _explode)

    try:
        result = await manager.check_seats_on_entry(CANONICAL)
    finally:
        SeatManager.reset_instance()
        RoomState.reset_instance()

    assert result is None
    assert seat_ui.expand_calls == 0
    assert seat_ui.collapse_calls == 0


async def test_check_seats_on_entry_without_a_handler_or_username_is_unchanged():
    """既有行为不许回归：没有 handler / 没有用户名都安静返回。"""
    assert await SeatSubsystem(handler=None).check_seats_on_entry(CANONICAL) is None

    handler = make_handler(controller=FakeController())
    subsystem = SeatSubsystem(handler)
    assert await subsystem.check_seats_on_entry(None) is None
    assert handler.logger.info.call_args_list == []
