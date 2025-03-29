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
        """Reserve a seat for a user"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}
            
        try:
            # Get or create user first
            user = await UserDAO.get_or_create(username)
            if not user:
                return {'error': f'Failed to get or create user {username}'}

            # Check if user already has a reservation
            existing_reservation = await SeatReservationDAO.get_user_reservation(user)
            if existing_reservation:
                return {'error': f'User {username} already has a reservation for seat {existing_reservation.seat_number}'}

            # Check if seat is already reserved
            existing_reservation = await SeatReservationDAO.get_seat_reservation(seat_number)
            if existing_reservation:
                return {'error': f'Seat {seat_number} is already reserved by {existing_reservation.user.username}'}

            # Expand seats if collapsed
            self.seat_ui.expand_seats()
            time.sleep(0.5)  # Wait for expansion animation

            # Get all seat containers
            seat_containers = self.handler.find_elements_plus('seat_container')
            if not seat_containers:
                return {'error': 'Cannot find seat containers'}

            # Find the target container based on seat number
            row_index = (seat_number - 1) // 4  # 0-based row index
            if row_index >= len(seat_containers):
                return {'error': f'Invalid seat number {seat_number}'}
                
            target_container = seat_containers[row_index]
            
            # Determine if this is a left or right seat in the row
            is_left_seat = (seat_number - 1) % 4 < 2
            
            # Find the specific seat element
            seat_element = None
            if is_left_seat:
                seat_element = self.handler.find_child_element_plus(target_container, 'left_seat')
                # Check if seat is already occupied
                left_state = self.handler.find_child_element_plus(target_container, 'left_state')
                if left_state:
                    return {'error': f'Seat {seat_number} is already occupied'}
            else:
                seat_element = self.handler.find_child_element_plus(target_container, 'right_seat')
                # Check if seat is already occupied
                right_state = self.handler.find_child_element_plus(target_container, 'right_state')
                if right_state:
                    return {'error': f'Seat {seat_number} is already occupied'}
                    
            if not seat_element:
                return {'error': f'Cannot find seat element for seat {seat_number}'}
                
            # Click the specific seat element
            seat_element.click()
            self.handler.logger.info(f"Clicked seat {seat_number}")

            # Wait for confirmation dialog
            confirm_button = self.handler.wait_for_element_clickable_plus('confirm_seat')
            if not confirm_button:
                return {'error': f'Failed to find confirm button for seat {seat_number}'}
            confirm_button.click()

            # Create reservation in database
            reservation = await SeatReservationDAO.create(user, seat_number, 24)

            return {'success': f'Successfully reserved seat {seat_number}'}

        except Exception as e:
            self.handler.log_error(f"Error reserving seat: {traceback.format_exc()}")
            return {'error': f'Failed to reserve seat: {str(e)}'}

    async def remove_user_reservation(self, username: str) -> dict:
        """Remove a user's seat reservation"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}
            
        try:
            # Get or create user first
            user = await UserDAO.get_or_create(username)
            if not user:
                return {'error': f'Failed to get or create user {username}'}

            # Get user's reservation
            reservation = await SeatReservationDAO.get_user_reservation(user)
            if not reservation:
                return {'error': f'No reservation found for user {username}'}

            # Expand seats if collapsed
            self.seat_ui.expand_seats()
            time.sleep(0.5)  # Wait for expansion animation

            # Get all seat containers
            seat_containers = self.handler.find_elements_plus('seat_container')
            if not seat_containers:
                return {'error': 'Cannot find seat containers'}

            # Find the target container based on seat number
            row_index = (reservation.seat_number - 1) // 4  # 0-based row index
            if row_index >= len(seat_containers):
                # Invalid seat number, just remove from database
                await SeatReservationDAO.remove_reservation(reservation)
                return {'success': f'Removed reservation for seat {reservation.seat_number} (invalid seat)'}
                
            target_container = seat_containers[row_index]
            
            # Determine if this is a left or right seat in the row
            is_left_seat = (reservation.seat_number - 1) % 4 < 2  # Seats 1,2,5,6,9,10 are left seats
            
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

            return {'success': f'Successfully removed reservation for seat {reservation.seat_number}'}

        except Exception as e:
            self.handler.log_error(f"Error removing reservation: {traceback.format_exc()}")
            return {'error': f'Failed to remove reservation: {str(e)}'}


