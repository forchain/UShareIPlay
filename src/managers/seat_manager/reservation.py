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

    async def remove_user_from_seat(self, username: str) -> dict:
        """Remove a user from their seat with UI interactions"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}
            
        try:
            # Get user's reservation
            user = await UserDAO.get_or_create(username)
            if not user:
                return {'error': f'Failed to get or create user {username}'}

            reservation = await SeatReservationDAO.get_reservation_by_user_id(user.id)
            if not reservation:
                return {'error': f'No reservation found for user {username}'}

            # Expand seats if collapsed
            self.seat_ui.expand_seats()
            time.sleep(0.5)  # Wait for expansion animation

            # Get all seat desks
            seat_desks = self.handler.find_elements_plus('seat_desk')
            if not seat_desks:
                return {'error': 'Cannot find seat desks'}

            # Find the target container based on seat number
            row_index = (reservation.seat_number - 1) // 4  # 0-based row index
            if row_index >= len(seat_desks):
                return {'error': f'Invalid seat number {reservation.seat_number}'}

            # Handle row visibility based on index
            if row_index == 0:  # First row
                # Scroll to show first row
                self.handler.scroll_to_element(seat_desks[0])
                time.sleep(0.5)
            elif row_index == 2:  # Third row
                # Scroll to show third row
                self.handler.scroll_to_element(seat_desks[2])
                time.sleep(0.5)
                
            target_container = seat_desks[row_index]
            
            # Determine if this is a left or right seat in the row
            is_left_seat = (reservation.seat_number - 1) % 4 < 2
            
            # Find the specific seat element
            seat_element = None
            if is_left_seat:
                seat_element = self.handler.find_child_element_plus(target_container, 'left_seat')
                # Check if seat is already empty
                left_state = self.handler.find_child_element_plus(target_container, 'left_state')
                if not left_state:
                    # Seat is already empty, just remove from database
                    await SeatReservationDAO.remove_reservation(reservation)
                    return {'success': f'Removed reservation for seat {reservation.seat_number} (already empty)'}
            else:
                seat_element = self.handler.find_child_element_plus(target_container, 'right_seat')
                # Check if seat is already empty
                right_state = self.handler.find_child_element_plus(target_container, 'right_state')
                if not right_state:
                    # Seat is already empty, just remove from database
                    await SeatReservationDAO.remove_reservation(reservation)
                    return {'success': f'Removed reservation for seat {reservation.seat_number} (already empty)'}
                    
            if not seat_element:
                # Seat element not found, just remove from database
                await SeatReservationDAO.remove_reservation(reservation)
                return {'success': f'Removed reservation for seat {reservation.seat_number} (seat not found)'}
                
            # Click the specific seat element
            seat_element.click()
            self.handler.logger.info(f"Clicked seat {reservation.seat_number} to remove reservation")

            # Wait for confirmation dialog
            confirm_button = self.handler.wait_for_element_clickable_plus('confirm_seat')
            if not confirm_button:
                return {'error': f'Failed to find confirm button for seat {reservation.seat_number}'}
            confirm_button.click()

            # Remove from database
            await SeatReservationDAO.remove_reservation(reservation)

            return {'success': f'Successfully removed user from seat {reservation.seat_number}'}

        except Exception as e:
            self.handler.log_error(f"Error removing user from seat: {traceback.format_exc()}")
            return {'error': f'Failed to remove user from seat: {str(e)}'}


