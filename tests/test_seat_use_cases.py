"""`SeatObservationService` 与 `SeatService` 用例层测试（纯替身，不依赖 Appium/Tortoise）。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pytest

from tests.fakes.in_memory_room_messenger import InMemoryRoomMessenger
from tests.fakes.in_memory_seat_reservation_repository import InMemorySeatReservationRepository
from tests.fakes.in_memory_ui_session import InMemoryUISession
from tests.fakes.in_memory_user_repository import InMemoryUserRepository
from ushareiplay.modules.room.domain import RoomAdmins, RoomState
from ushareiplay.modules.seat.domain import (
    GUEST_ROOM_ERROR_RESULT,
    AvatarTapPolicy,
    DeskSnapshot,
    Reading,
    SeatCardView,
    SeatInviteRow,
)
from ushareiplay.modules.seat.ports import SeatInvitePort, SeatPanelPort
from ushareiplay.modules.seat.use_cases import SeatObservationService, SeatService


def _empty_reading(seat_number: int) -> Reading:
    return Reading(
        occupied=False,
        is_empty=True,
        label=str(seat_number),
        has_state=False,
        has_default=True,
        has_rank=False,
        avatar_images=1,
    )


def _occupied_reading(label: str) -> Reading:
    return Reading(
        occupied=True,
        is_empty=False,
        label=label,
        has_state=True,
        has_default=False,
        has_rank=False,
        avatar_images=4,
    )


def _desk(
    desk_index: int,
    left: Reading,
    right: Reading,
    *,
    y: Optional[int] = None,
    interactable: bool = True,
) -> DeskSnapshot:
    row = desk_index // 2
    col = desk_index % 2
    y_pos = y if y is not None else 566 + row * 234
    x_pos = 28 + col * 355
    return DeskSnapshot(
        desk_id=f"desk-{desk_index}",
        bounds={"x": x_pos, "y": y_pos, "width": 309, "height": 207 if interactable else 18},
        displayed=True,
        left=left,
        right=right,
        left_has_seat=True,
        right_has_seat=True,
        interactable=interactable,
    )


class FakeSeatPanel(SeatPanelPort):
    def __init__(self, ui_session: Optional[InMemoryUISession] = None):
        self._ui_session = ui_session or InMemoryUISession()
        self.expanded = False
        self.desks_to_return: Optional[List[DeskSnapshot]] = None
        self.page_source_desks: List[DeskSnapshot] = []
        self.focus_count: Optional[int] = None
        self.occupant_names: Dict[int, Optional[str]] = {}
        self.on_read_occupant = None
        self.click_empty_error: Optional[str] = None
        self.confirm_result: dict = {"success": "Successfully took a seat"}
        self.seat_off_button_error: Optional[str] = None
        self.clicked_empty_seats: List[tuple] = []
        self.seat_off_clicked: List[int] = []

    @property
    def holds_session(self) -> bool:
        return self._ui_session.holds_session

    @property
    def busy_elsewhere(self) -> bool:
        return self._ui_session.busy_elsewhere

    @property
    def can_probe_ui(self) -> bool:
        return self.holds_session or not self.busy_elsewhere

    def session(self, reason: str = "", *, skip_if_busy: bool = False):
        return self._ui_session.acquire(reason, skip_if_busy=skip_if_busy)

    @property
    def is_handler_ready(self) -> bool:
        return True

    def is_expanded(self) -> bool:
        return self.expanded

    async def expand(self) -> bool:
        self.expanded = True
        return True

    async def collapse(self) -> bool:
        self.expanded = False
        return True

    async def expand_and_find_desk_snapshots(self) -> Optional[List[DeskSnapshot]]:
        self.expanded = True
        return self.desks_to_return

    def scroll_to_row(self, desk_index: int, seat_desks=None, duration: int = 100) -> bool:
        return desk_index // 2 != 1

    def snapshot_desks(self, raw_desks: list) -> List[DeskSnapshot]:
        return list(raw_desks)

    def find_on_screen_desks(self) -> List[DeskSnapshot]:
        return list(self.desks_to_return or [])

    def read_page_source_desks(self, page_source: Optional[str] = None) -> List[DeskSnapshot]:
        return list(self.page_source_desks)

    def read_focus_count(self) -> Optional[int]:
        return self.focus_count

    async def read_occupant(self, desk_id: str, side: str, seat_number: int) -> Optional[str]:
        if self.on_read_occupant is not None:
            await self.on_read_occupant(seat_number)
        return self.occupant_names.get(seat_number)

    @asynccontextmanager
    async def avatar_card(
        self,
        desk_id: str,
        side: str,
        seat_number: int,
        *,
        tap_target: AvatarTapPolicy = AvatarTapPolicy.STATE_THEN_SEAT,
    ):
        name = self.occupant_names.get(seat_number)
        yield SeatCardView(opened=name is not None, name=name)

    def click_empty_seat(self, desk_id: str, side: str) -> Optional[str]:
        self.clicked_empty_seats.append((desk_id, side))
        return self.click_empty_error

    def confirm_seat(self) -> dict:
        return dict(self.confirm_result)

    def take_seat_by_element(self, desk_id: str, side: str) -> dict:
        return dict(self.confirm_result)

    def seat_off_by_element(self, desk_id: str, side: str, seat_number: int) -> dict:
        return {"success": f"Successfully removed User from seat {seat_number}"}

    def click_seat_off_button(self, seat_number: int) -> Optional[str]:
        if self.seat_off_button_error is None:
            self.seat_off_clicked.append(seat_number)
        return self.seat_off_button_error


class FakeSeatInvite(SeatInvitePort):
    def __init__(self, rows: Optional[List[SeatInviteRow]] = None):
        self.rows = rows or []
        self.open = True
        self.invited: List[str] = []
        self.closed = False

    async def wait_until_open(self, timeout: float = 3.0) -> bool:
        return self.open

    async def find_row(self, visible_name: str, max_pages: int = 10) -> Optional[SeatInviteRow]:
        for row in self.rows:
            if row.name == visible_name:
                return row
        return None

    def click_invite(self, row: SeatInviteRow) -> bool:
        if not row.invitable:
            return False
        self.invited.append(row.name)
        return True

    def close(self) -> bool:
        self.closed = True
        return True


@pytest.mark.asyncio
async def test_gate_lock_is_never_held_across_popup_awaits():
    """核心并发铁律：弹窗 await（read_occupant）期间绝不持有 gate_state.lock。"""
    panel = FakeSeatPanel()
    obs = SeatObservationService(panel=panel)
    lock_held_during_popup: List[bool] = []

    async def _check_lock(seat_number: int):
        lock_held_during_popup.append(obs.ledger.gate_state.lock.locked())
        # 验证在弹窗 await 期间，另一个协程可以立即获取 gate_state.lock 做并发同步而不死锁
        async with asyncio.timeout(0.2):
            async with obs.ledger.gate_state.lock:
                pass

    panel.on_read_occupant = _check_lock
    panel.occupant_names[1] = "Alice"

    desks = [
        _desk(0, _occupied_reading("1"), _empty_reading(2)),
        _desk(1, _empty_reading(3), _empty_reading(4)),
    ]
    await obs.observe_visible_desks(desks, current_focus_count=1)

    assert lock_held_during_popup == [False]
    assert obs.get_user_seat("Alice") == 1


@pytest.mark.asyncio
async def test_reserve_and_remove_reservation_use_cases():
    users = InMemoryUserRepository()
    reservations = InMemorySeatReservationRepository()
    panel = FakeSeatPanel()
    invite = FakeSeatInvite()
    room_state = RoomState()
    svc = SeatService(
        panel=panel,
        invite_driver=invite,
        reservations=reservations,
        users=users,
        room_state=room_state,
        messenger=InMemoryRoomMessenger(),
    )

    alice = await users.get_or_create("Alice")
    await users.update_level(alice.id, 3)
    reservations.seed_user(alice.id, "Alice", level=3)

    res = await svc.reserve_seat("Alice", 5)
    assert res == {"success": "Successfully reserved seat 5 for 3 hours"}

    bob = await users.get_or_create("Bob")
    await users.update_level(bob.id, 2)
    reservations.seed_user(bob.id, "Bob", level=2)
    denied = await svc.reserve_seat("Bob", 5)
    assert denied == {"error": "Seat 5 is already reserved by Alice with level 3"}

    removed = await svc.remove_user_reservation("Alice")
    assert removed == {"success": "Successfully removed reservation for seat 5"}


@pytest.mark.asyncio
async def test_guest_room_guard_blocks_seat_service():
    room_state = RoomState()
    room_state.is_guest_room = True
    svc = SeatService(
        panel=FakeSeatPanel(),
        invite_driver=FakeSeatInvite(),
        reservations=InMemorySeatReservationRepository(),
        users=InMemoryUserRepository(),
        room_state=room_state,
    )

    assert await svc.reserve_seat("Alice", 1) == GUEST_ROOM_ERROR_RESULT
    assert await svc.take_seat(1) == GUEST_ROOM_ERROR_RESULT
    assert await svc.invite_user_to_seat(1, "Alice") == GUEST_ROOM_ERROR_RESULT
    assert await svc.prepare_for_chat_scan() is True


@pytest.mark.asyncio
async def test_auto_invite_reentrant_ui_session_and_invite_flow():
    ui_session = InMemoryUISession()
    panel = FakeSeatPanel(ui_session=ui_session)
    desks = [_desk(i, _empty_reading(i * 2 + 1), _empty_reading(i * 2 + 2)) for i in range(6)]
    panel.desks_to_return = desks
    panel.page_source_desks = desks

    invite = FakeSeatInvite(rows=[SeatInviteRow(name="可见Alice", operation="邀请", invitable=True)])
    users = InMemoryUserRepository()
    reservations = InMemorySeatReservationRepository()
    messenger = InMemoryRoomMessenger()
    obs = SeatObservationService(panel=panel)

    async def _resolve(name: str) -> str:
        return "可见Alice" if name == "Alice" else name

    svc = SeatService(
        panel=panel,
        invite_driver=invite,
        reservations=reservations,
        users=users,
        observation=obs,
        messenger=messenger,
        resolve_visible_username=_resolve,
    )

    await svc.check_seats_on_entry("Alice")

    assert invite.invited == ["可见Alice"]
    assert invite.closed is True
    assert panel.expanded is False
    assert messenger.messages == ["已邀请 可见Alice 入座 1 号座位"]
