from datetime import datetime, timedelta
from ..dal import UserDAO, SeatReservationDAO
import re

class SeatManager:
    _instance = None
    _initialized = False

    def __new__(cls, handler=None):
        if cls._instance is None:
            cls._instance = super(SeatManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, handler=None):
        if not self._initialized:
            self.handler = handler
            self.previous_focus_count = None
            self.previous_seat_states = {}  # Store previous seat states
            self._initialized = True

    @classmethod
    def get_instance(cls):
        """Get the singleton instance"""
        if cls._instance is None:
            raise RuntimeError("SeatManager has not been initialized. Call SeatManager(handler) first.")
        return cls._instance

    def update(self):
        """Update seat states and check for changes"""
        self.check_focus_count()

    def check_focus_count(self):
        """Check the focus count and execute seating if it changes."""
        focus_count_element = self.handler.try_find_element_plus('focus_count', log=False)
        if not focus_count_element:
            return

        current_focus_count_text = focus_count_element.text
        match = re.search(r'(\d+)人专注中', current_focus_count_text)
        if not match:
            return

        current_focus_count = int(match.group(1))
        if self.previous_focus_count == current_focus_count:
            return

        self.previous_focus_count = current_focus_count
        self.handler.logger.info(f"Focus count changed to: {current_focus_count}. Checking seat changes.")
        self._check_seat_changes()

    def _check_seat_changes(self):
        """Check for seat changes and handle events"""
        try:
            # Expand seats if needed
            self.expand_seats()

            # Get current seat states
            current_seat_states = {}
            seat_containers = self.handler.find_elements_plus('seat_container')
            
            for container in seat_containers:
                seat_number = self._get_seat_number(container)
                if not seat_number:
                    continue

                left_state = self.handler.find_child_element_plus(container, 'left_state')
                right_state = self.handler.find_child_element_plus(container, 'right_state')
                left_label = self.handler.find_child_element_plus(container, 'left_label')
                right_label = self.handler.find_child_element_plus(container, 'right_label')

                current_seat_states[seat_number] = {
                    'left': {
                        'occupied': bool(left_state),
                        'username': left_label.text if left_label else None
                    },
                    'right': {
                        'occupied': bool(right_state),
                        'username': right_label.text if right_label else None
                    }
                }

            # Compare with previous states
            for seat_number, states in current_seat_states.items():
                if seat_number not in self.previous_seat_states:
                    continue

                prev_states = self.previous_seat_states[seat_number]
                
                # Check left seat changes
                if states['left']['occupied'] != prev_states['left']['occupied']:
                    if states['left']['occupied']:
                        self._handle_seat_taken(seat_number, 'left', states['left']['username'])
                    else:
                        self._handle_seat_left(seat_number, 'left', prev_states['left']['username'])

                # Check right seat changes
                if states['right']['occupied'] != prev_states['right']['occupied']:
                    if states['right']['occupied']:
                        self._handle_seat_taken(seat_number, 'right', states['right']['username'])
                    else:
                        self._handle_seat_left(seat_number, 'right', prev_states['right']['username'])

            # Update previous states
            self.previous_seat_states = current_seat_states

        except Exception as e:
            self.handler.log_error(f"Error checking seat changes: {str(e)}")

    async def _handle_seat_taken(self, seat_number: int, side: str, username: str):
        """Handle when someone takes a seat"""
        try:
            # Check if seat is reserved
            reservation = await SeatReservationDAO.get_active_by_seat(seat_number)
            if reservation:
                # Check if the user taking the seat has higher level
                user = await UserDAO.get_or_create(username)
                if user.level > reservation.user.level:
                    # Higher level user took the seat
                    self.handler.send_message(f"{username} (Level {user.level}) took seat {seat_number} from {reservation.user.username} (Level {reservation.user.level})")
                    # Remove the reservation
                    await SeatReservationDAO.remove_reservation(reservation.id)
                else:
                    # Lower level user trying to take reserved seat
                    self.handler.send_message(f"Seat {seat_number} is reserved by {reservation.user.username} (Level {reservation.user.level}). {username} (Level {user.level}) will be removed.")
                    # Remove the lower level user
                    await self._remove_user_from_seat(seat_number, side)
            else:
                self.handler.send_message(f"{username} took seat {seat_number}")

        except Exception as e:
            self.handler.log_error(f"Error handling seat taken: {str(e)}")

    async def _handle_seat_left(self, seat_number: int, side: str, username: str):
        """Handle when someone leaves a seat"""
        try:
            if username:
                self.handler.send_message(f"{username} left seat {seat_number}")
                # Check if user has active reservation
                user = await UserDAO.get_or_create(username)
                reservation = await SeatReservationDAO.get_active_by_seat(seat_number)
                if reservation and reservation.user.id == user.id:
                    # Update reservation with new start time
                    await SeatReservationDAO.update_reservation_start_time(reservation.id, datetime.now())

        except Exception as e:
            self.handler.log_error(f"Error handling seat left: {str(e)}")

    async def _remove_user_from_seat(self, seat_number: int, side: str):
        """Remove a user from a specific seat"""
        try:
            # Find the seat container
            seat_containers = self.handler.find_elements_plus('seat_container')
            for container in seat_containers:
                if self._get_seat_number(container) == seat_number:
                    # Find the seat down button
                    seat_down = self.handler.find_child_element_plus(container, 'seat_down')
                    if seat_down:
                        seat_down.click()
                        self.handler.logger.info(f"Removed user from seat {seat_number}")
                    break
        except Exception as e:
            self.handler.log_error(f"Error removing user from seat: {str(e)}")

    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        """Reserve a seat for a user"""
        try:
            # Get or create user
            user = await UserDAO.get_or_create(username)
            
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

    async def check_and_remove_users(self):
        """Check and remove users from reserved seats"""
        try:
            # Get all active reservations
            reservations = await SeatReservationDAO.get_active_reservations()
            if not reservations:
                return

            # Expand seats if needed
            self.expand_seats()

            # Get all seat containers
            seat_containers = self.handler.find_elements_plus('seat_container')
            if not seat_containers:
                return

            for reservation in reservations:
                seat_number = reservation.seat_number
                target_container = None
                
                # Find the target container based on seat number
                if seat_number <= 4:  # First row
                    target_container = seat_containers[0]
                elif seat_number <= 8:  # Second row
                    target_container = seat_containers[1]
                else:  # Third row
                    target_container = seat_containers[2]

                if not target_container:
                    continue

                # Check if seat is empty
                empty_seat = self.handler.find_child_element_plus(target_container, 'empty_seat')
                if empty_seat:
                    continue

                # Check both left and right seats
                for side in ['left', 'right']:
                    state = self.handler.find_child_element_plus(target_container, f'{side}_state')
                    if state:
                        # Click state to open profile
                        state.click()
                        # Find and click seat off button
                        seat_off = self.handler.wait_for_element_clickable_plus('seat_off')
                        if seat_off:
                            seat_off.click()
                            self.handler.logger.info(f"Removed user from seat {seat_number}")
                            break

        except Exception as e:
            self.handler.log_error(f"Error checking and removing users: {str(e)}")

    def _get_seat_number(self, container):
        """Get seat number from container"""
        try:
            # This is a placeholder - you'll need to implement the actual logic
            # to determine the seat number from the container
            return 1
        except:
            return None

    def expand_seats(self):
        """Expand seats if collapsed"""
        expand_seats = self.handler.try_find_element_plus('expand_seats', log=False)
        if expand_seats and expand_seats.text == '展开座位':
            expand_seats.click()
            self.handler.logger.info(f'Expanded seats')
    
    def collapse_seats(self):
        """Collapse seats if expanded"""
        expand_seats = self.handler.try_find_element_plus('expand_seats', log=False)
        if expand_seats and expand_seats.text == '收起座位':
            expand_seats.click()
            self.handler.logger.info(f'Collapsed seats')

    async def get_user_reservations(self, username: str) -> list:
        """Get all active reservations for a user"""
        try:
            user = await UserDAO.get_or_create(username)
            reservations = await SeatReservationDAO.get_user_reservations(user)
            return reservations
        except Exception as e:
            self.handler.log_error(f"Error getting user reservations: {str(e)}")
            return [] 