from datetime import datetime, timedelta
from ..dal import UserDAO, SeatReservationDAO
from .base import SeatManagerBase
from .seat_ui import SeatUIManager

class ReservationManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.seat_ui = SeatUIManager(handler)

    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        """Reserve a seat for a user"""
        try:
            # Get or create user
            user = await UserDAO.get_or_create(username)
            
            # First, remove any existing reservations for this user
            await SeatReservationDAO.remove_user_reservations(user)
            
            # Check if seat is already reserved
            existing_reservation = await SeatReservationDAO.get_active_by_seat(seat_number)
            
            if not existing_reservation:
                # Seat is not reserved, create new reservation
                reservation = await SeatReservationDAO.create(
                    user=user,
                    seat_number=seat_number,
                    duration_hours=user.level
                )
                return {'success': f'Seat {seat_number} reserved for {user.level} hours'}
            
            # Check if reservation is expired
            end_time = existing_reservation.start_time + timedelta(hours=existing_reservation.duration_hours)
            if datetime.now() > end_time:
                # Reservation expired, create new one
                await SeatReservationDAO.remove_reservation(existing_reservation.id)
                reservation = await SeatReservationDAO.create(
                    user=user,
                    seat_number=seat_number,
                    duration_hours=user.level
                )
                return {'success': f'Seat {seat_number} reserved for {user.level} hours'}

            # Check user levels
            if user.level > existing_reservation.user.level:
                # Higher level user, replace reservation
                await SeatReservationDAO.remove_reservation(existing_reservation.id)
                reservation = await SeatReservationDAO.create(
                    user=user,
                    seat_number=seat_number,
                    duration_hours=user.level
                )
                return {'success': f'Seat {seat_number} reserved for {user.level} hours'}
            else:
                # Lower level user, show remaining time
                remaining_time = end_time - datetime.now()
                remaining_hours = remaining_time.total_seconds() / 3600
                return {'error': f'Seat {seat_number} is reserved by {existing_reservation.user.username} (Level {existing_reservation.user.level}) for {remaining_hours:.1f} more hours'}

        except Exception as e:
            self.handler.log_error(f"Error reserving seat: {str(e)}")
            return {'error': f'Failed to reserve seat: {str(e)}'}

    async def remove_user_reservation(self, username: str) -> dict:
        """Remove all reservations for a user"""
        try:
            user = await UserDAO.get_or_create(username)
            success = await SeatReservationDAO.remove_user_reservations(user)
            if success:
                return {'success': f'Removed all reservations for {username}'}
            return {'error': f'Failed to remove reservations for {username}'}
        except Exception as e:
            self.handler.log_error(f"Error removing user reservations: {str(e)}")
            return {'error': f'Failed to remove reservations: {str(e)}'}

    async def get_user_reservation(self, username: str):
        """Get the latest reservation for a user"""
        try:
            user = await UserDAO.get_or_create(username)
            reservation = await SeatReservationDAO.get_user_reservation(user)
            return reservation
        except Exception as e:
            self.handler.log_error(f"Error getting user reservation: {str(e)}")
            return None

    async def be_seated(self) -> dict:
        """Find and take an available seat, prioritizing seats with neighbors"""
        try:
            # Expand seats if needed
            self.seat_ui.expand_seats()

            # Get all seat containers
            seat_containers = self.handler.find_elements_plus('seat_container')
            if not seat_containers:
                return {'error': 'No seat containers found'}

            # First try to find a seat with neighbors
            for container in seat_containers:
                seat_number = self.seat_ui._get_seat_number(container)
                if not seat_number:
                    continue

                # Check if this seat is empty
                empty_seat = self.handler.find_child_element_plus(container, 'empty_seat')
                if not empty_seat:
                    continue

                # Check if there are neighbors (either left or right seat is occupied)
                left_state = self.handler.find_child_element_plus(container, 'left_state')
                right_state = self.handler.find_child_element_plus(container, 'right_state')
                
                if bool(left_state) or bool(right_state):
                    # Found a seat with neighbors, take it
                    empty_seat.click()
                    self.handler.logger.info(f"Took seat {seat_number} with neighbors")
                    return {'success': f'Took seat {seat_number}'}

            # If no seat with neighbors found, take any empty seat
            for container in seat_containers:
                seat_number = self.seat_ui._get_seat_number(container)
                if not seat_number:
                    continue

                empty_seat = self.handler.find_child_element_plus(container, 'empty_seat')
                if empty_seat:
                    empty_seat.click()
                    self.handler.logger.info(f"Took empty seat {seat_number}")
                    return {'success': f'Took seat {seat_number}'}

            return {'error': 'No available seats found'}
        except Exception as e:
            self.handler.log_error(f"Error finding seat: {str(e)}")
            return {'error': f'Failed to find seat: {str(e)}'} 