"""`SeatReservationRepository` 的 Tortoise ORM 实现。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from ushareiplay.adapters.outbound.persistence.models import SeatReservation as SeatReservationModel
from ushareiplay.adapters.outbound.persistence.models import User as UserModel
from ushareiplay.modules.seat.domain import SeatReservation
from ushareiplay.modules.seat.ports import SeatReservationRepository

logger = logging.getLogger("seat_dao")


class TortoiseSeatReservationRepository(SeatReservationRepository):
    """基于 Tortoise ORM 的座位预约仓储。"""

    @staticmethod
    def _to_domain(row: SeatReservationModel) -> SeatReservation:
        user = getattr(row, "user", None)
        username = getattr(user, "username", "") if user is not None else ""
        user_level = getattr(user, "level", 0) if user is not None else 0
        start_time = row.start_time
        if start_time.tzinfo is not None:
            start_time = start_time.replace(tzinfo=None)
        return SeatReservation(
            id=row.id,
            user_id=row.user_id,
            username=username,
            user_level=user_level,
            seat_number=row.seat_number,
            start_time=start_time,
            duration_hours=row.duration_hours,
        )

    async def create(
        self,
        user_id: int,
        seat_number: int,
        duration_hours: int,
        start_time: Optional[datetime] = None,
    ) -> SeatReservation:
        user = await UserModel.get(id=user_id)
        row = await SeatReservationModel.create(
            user=user,
            seat_number=seat_number,
            start_time=start_time or datetime.now(),
            duration_hours=duration_hours,
        )
        await row.fetch_related("user")
        return self._to_domain(row)

    async def get_by_user_id(self, user_id: int) -> Optional[SeatReservation]:
        row = (
            await SeatReservationModel.filter(user__id=user_id)
            .prefetch_related("user")
            .order_by("-created_at", "-id")
            .first()
        )
        return None if row is None else self._to_domain(row)

    async def get_by_seat_number(self, seat_number: int) -> Optional[SeatReservation]:
        row = (
            await SeatReservationModel.filter(seat_number=seat_number)
            .prefetch_related("user")
            .first()
        )
        return None if row is None else self._to_domain(row)

    async def get_active_reservations(
        self, now: Optional[datetime] = None
    ) -> List[SeatReservation]:
        current = now or datetime.now()
        rows = (
            await SeatReservationModel.filter(
                start_time__lte=current,
                start_time__gte=current - timedelta(hours=24),
            )
            .prefetch_related("user")
            .all()
        )
        active: List[SeatReservation] = []
        for row in rows:
            domain_row = self._to_domain(row)
            end_time = domain_row.start_time + timedelta(hours=domain_row.duration_hours)
            if current <= end_time:
                active.append(domain_row)
        return active

    async def remove_by_id(self, reservation_id: int) -> bool:
        deleted = await SeatReservationModel.filter(id=reservation_id).delete()
        return deleted > 0

    async def update_start_time(
        self, reservation_id: int, new_start_time: datetime
    ) -> Optional[SeatReservation]:
        row = await SeatReservationModel.get_or_none(id=reservation_id).prefetch_related("user")
        if row is None:
            return None
        row.start_time = new_start_time
        await row.save()
        return self._to_domain(row)

    async def remove_by_user_id(self, user_id: int) -> bool:
        await SeatReservationModel.filter(user_id=user_id).delete()
        return True
