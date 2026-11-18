"""`SeatReservationRepository` 的内存替身，供单测与契约套件使用。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from ushareiplay.modules.seat.domain import SeatReservation
from ushareiplay.modules.seat.ports import SeatReservationRepository


class InMemorySeatReservationRepository(SeatReservationRepository):
    """纯内存座位预约仓储。"""

    def __init__(self, user_lookup: Optional[Callable[[int], Tuple[str, int]]] = None):
        self._records: Dict[int, SeatReservation] = {}
        self._next_id = 1
        self._user_lookup = user_lookup or (lambda uid: (f"user_{uid}", 1))

    def seed_user(self, user_id: int, username: str, level: int = 1) -> None:
        """为内存替身登记用户信息（不依赖外部 UserRepository）。"""
        if not hasattr(self, "_users"):
            self._users: Dict[int, Tuple[str, int]] = {}
        self._users[user_id] = (username, level)

    def _resolve_user(self, user_id: int) -> Tuple[str, int]:
        if hasattr(self, "_users") and user_id in self._users:
            return self._users[user_id]
        return self._user_lookup(user_id)

    async def create(
        self,
        user_id: int,
        seat_number: int,
        duration_hours: int,
        start_time: Optional[datetime] = None,
    ) -> SeatReservation:
        username, user_level = self._resolve_user(user_id)
        st = start_time or datetime.now()
        if st.tzinfo is not None:
            st = st.replace(tzinfo=None)
        record = SeatReservation(
            id=self._next_id,
            user_id=user_id,
            username=username,
            user_level=user_level,
            seat_number=seat_number,
            start_time=st,
            duration_hours=duration_hours,
        )
        self._records[self._next_id] = record
        self._next_id += 1
        return record

    async def get_by_user_id(self, user_id: int) -> Optional[SeatReservation]:
        matches = [r for r in self._records.values() if r.user_id == user_id]
        if not matches:
            return None
        return matches[-1]

    async def get_by_seat_number(self, seat_number: int) -> Optional[SeatReservation]:
        for r in self._records.values():
            if r.seat_number == seat_number:
                return r
        return None

    async def get_active_reservations(
        self, now: Optional[datetime] = None
    ) -> List[SeatReservation]:
        current = now or datetime.now()
        active: List[SeatReservation] = []
        for r in self._records.values():
            if r.start_time <= current <= r.start_time + timedelta(hours=r.duration_hours):
                active.append(r)
        return active

    async def remove_by_id(self, reservation_id: int) -> bool:
        return self._records.pop(reservation_id, None) is not None

    async def update_start_time(
        self, reservation_id: int, new_start_time: datetime
    ) -> Optional[SeatReservation]:
        old = self._records.get(reservation_id)
        if old is None:
            return None
        st = new_start_time.replace(tzinfo=None) if new_start_time.tzinfo else new_start_time
        updated = SeatReservation(
            id=old.id,
            user_id=old.user_id,
            username=old.username,
            user_level=old.user_level,
            seat_number=old.seat_number,
            start_time=st,
            duration_hours=old.duration_hours,
        )
        self._records[reservation_id] = updated
        return updated

    async def remove_by_user_id(self, user_id: int) -> bool:
        to_delete = [rid for rid, r in self._records.items() if r.user_id == user_id]
        for rid in to_delete:
            del self._records[rid]
        return True
