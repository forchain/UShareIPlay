from typing import Optional, List
from datetime import datetime, timedelta
from src.models import SeatReservation, User

class SeatReservationDAO:
    @staticmethod
    async def create(user: User, seat_number: int, duration_hours: int) -> SeatReservation:
        """Create a new seat reservation"""
        return await SeatReservation.create(
            user=user,
            seat_number=seat_number,
            start_time=datetime.now(),
            duration_hours=duration_hours
        )

    @staticmethod
    async def get_active_by_seat(seat_number: int) -> Optional[SeatReservation]:
        """Get active reservation for a specific seat"""
        now = datetime.now()
        reservation = await SeatReservation.filter(
            seat_number=seat_number,
            start_time__lte=now,
            start_time__gte=now - timedelta(hours=24)
        ).first()
        
        if reservation:
            end_time = reservation.start_time + timedelta(hours=reservation.duration_hours)
            if now > end_time:
                return None
        return reservation

    @staticmethod
    async def get_user_reservations(user: User) -> List[SeatReservation]:
        """Get all active reservations for a user"""
        now = datetime.now()
        return await SeatReservation.filter(
            user=user,
            start_time__lte=now,
            start_time__gte=now - timedelta(hours=24)
        ).all()

    @staticmethod
    async def get_active_reservations() -> List[SeatReservation]:
        """Get all active reservations"""
        now = datetime.now()
        return await SeatReservation.filter(
            start_time__lte=now,
            start_time__gte=now - timedelta(hours=24)
        ).all()

    @staticmethod
    async def remove_reservation(reservation_id: int) -> bool:
        """Remove a reservation by ID"""
        try:
            reservation = await SeatReservation.get_or_none(id=reservation_id)
            if reservation:
                await reservation.delete()
                return True
            return False
        except Exception:
            return False

    @staticmethod
    async def update_reservation_start_time(reservation_id: int, new_start_time: datetime) -> Optional[SeatReservation]:
        """Update the start time of a reservation"""
        try:
            reservation = await SeatReservation.get_or_none(id=reservation_id)
            if reservation:
                reservation.start_time = new_start_time
                await reservation.save()
            return reservation
        except Exception:
            return None 