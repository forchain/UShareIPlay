from datetime import datetime, timedelta
from ...dal import UserDAO, SeatReservationDAO
from ...models import User
from .base import SeatManagerBase
from .seat_ui import SeatUIManager
import time
import traceback

class ReservationManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.seat_ui = SeatUIManager(handler)

    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        """Reserve a seat for a user (data operation only)"""
        try:
            # Get or create user first
            user = await UserDAO.get_or_create(username)
            if not user:
                return {'error': f'Failed to get or create user {username}'}

            # Remove any existing reservation for the user
            existing_reservation = await SeatReservationDAO.get_reservation_by_user_id(user.id)
            if existing_reservation:
                await SeatReservationDAO.remove_reservation(existing_reservation)

            # Check if seat is already reserved
            existing_reservation = await SeatReservationDAO.get_seat_reservation(seat_number)
            if existing_reservation:
                # If the seat is reserved, check if current user has higher level
                if user.level <= existing_reservation.user.level:
                    return {'error': f'Seat {seat_number} is already reserved by {existing_reservation.user.username} with level {existing_reservation.user.level}'}
                # If current user has higher level, remove the existing reservation
                await SeatReservationDAO.remove_reservation(existing_reservation)

            # Create reservation in database
            duration_hours = min(max(user.level, 1), 24)  # Duration is user's level, between 1 and 24 hours
            reservation = await SeatReservationDAO.create(user, seat_number, duration_hours)

            return {'success': f'Successfully reserved seat {seat_number} for {duration_hours} hours'}

        except Exception as e:
            self.handler.log_error(f"Error reserving seat: {traceback.format_exc()}")
            return {'error': f'Failed to reserve seat: {str(e)}'}

    async def remove_user_reservation(self, username: str) -> dict:
        """Remove a user's seat reservation (data operation only)"""
        try:
            # Get or create user first
            user = await UserDAO.get_or_create(username)
            if not user:
                return {'error': f'Failed to get or create user {username}'}

            # Get user's reservation
            reservation = await SeatReservationDAO.get_reservation_by_user_id(user.id)
            if not reservation:
                return {'error': f'No reservation found for user {username}'}

            # Remove from database
            await SeatReservationDAO.remove_reservation(reservation)

            return {'success': f'Successfully removed reservation for seat {reservation.seat_number}'}

        except Exception as e:
            self.handler.log_error(f"Error removing reservation: {traceback.format_exc()}")
            return {'error': f'Failed to remove reservation: {str(e)}'}



