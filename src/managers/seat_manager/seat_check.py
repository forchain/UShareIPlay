import time
import traceback
from datetime import datetime, timedelta
from ...dal import UserDAO, SeatReservationDAO
from .base import SeatManagerBase

class SeatCheckManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.seat_ui = None  # Will be set when needed through SeatManager instance

    async def check_seats_on_entry(self, username: str = None):
        """Check seats when user enters the party"""
        try:
            # Ensure seats are expanded first
            self.seat_ui.expand_seats()
            time.sleep(0.5)  # Wait for expansion animation

            # Get all seat containers
            seat_containers = self.handler.find_elements_plus('seat_container')
            if not seat_containers:
                return

            # If username is provided, check their specific seat first
            if username:
                await self._check_user_specific_seat(username, seat_containers)
                return

            # If no specific seat to check, check all seats
            await self._check_all_seats(seat_containers)

        except Exception as e:
            self.handler.log_error(f"Error checking seats: {traceback.format_exc()}")

    async def _check_user_specific_seat(self, username: str, seat_containers):
        """Check and handle a specific user's seat"""
        user_reservation = await SeatReservationDAO.get_user_reservation(User(username=username))
        if not user_reservation:
            return

        seat_number = user_reservation.seat_number
        await self._scroll_to_seat_row(seat_number, seat_containers)
        
        target_container = self._find_seat_container(seat_containers, seat_number)
        if target_container:
            await self._handle_occupied_seat(target_container, seat_number)

    async def _scroll_to_seat_row(self, seat_number: int, seat_containers):
        """Scroll to the row containing the target seat"""
        # Calculate row (1-3) and position (1-4)
        row = (seat_number - 1) // 4 + 1
        position = (seat_number - 1) % 4 + 1
        
        # Get first container for height reference
        container = seat_containers[0]
        seat_height = container.size['height']
        
        # Scroll based on row
        if row == 1:
            # First row - scroll down
            self.handler.driver.swipe(
                container.location['x'] + container.size['width'] // 2,
                container.location['y'] + container.size['height'] // 2,
                container.location['x'] + container.size['width'] // 2,
                container.location['y'] + container.size['height'] // 2 + seat_height,
                1000
            )
        elif row == 3:
            # Third row - scroll up
            self.handler.driver.swipe(
                container.location['x'] + container.size['width'] // 2,
                container.location['y'] + container.size['height'] // 2,
                container.location['x'] + container.size['width'] // 2,
                container.location['y'] + container.size['height'] // 2 - seat_height,
                1000
            )
        
        # Wait for scroll to complete
        time.sleep(0.5)

    def _find_seat_container(self, seat_containers, seat_number: int):
        """Find the container for a specific seat number"""
        for container in seat_containers:
            seat_number_element = self.handler.find_child_element_plus(container, 'seat_number')
            if seat_number_element and seat_number_element.text == str(seat_number):
                return container
        return None

    async def _handle_occupied_seat(self, container, seat_number: int):
        """Handle an occupied seat by removing the occupant"""
        left_state = self.handler.find_child_element_plus(container, 'left_state')
        right_state = self.handler.find_child_element_plus(container, 'right_state')
        
        if left_state or right_state:
            # Click the seat to remove occupant
            if not self.handler.click_element_at(container, x_ratio=0.5, y_ratio=0.5):
                self.handler.log_error(f"Failed to click seat {seat_number}")
                return
            
            # Wait for confirmation dialog
            confirm_button = self.handler.wait_for_element_clickable_plus('confirm_button')
            if confirm_button:
                confirm_button.click()
                self.handler.logger.info(f"Removed occupant from seat {seat_number}")
            else:
                self.handler.log_error(f"Failed to find confirm button for seat {seat_number}")

    async def _check_all_seats(self, seat_containers):
        """Check and handle all occupied seats"""
        for container in seat_containers:
            seat_number_element = self.handler.find_child_element_plus(container, 'seat_number')
            if not seat_number_element:
                continue
                
            try:
                seat_number = int(seat_number_element.text)
            except ValueError:
                continue

            left_state = self.handler.find_child_element_plus(container, 'left_state')
            right_state = self.handler.find_child_element_plus(container, 'right_state')
            
            if left_state or right_state:
                await self._handle_occupied_seat(container, seat_number)

    async def check_and_remove_users(self):
        """Check and remove users from reserved seats"""
        try:
            # Get all active reservations
            reservations = await SeatReservationDAO.get_active_reservations()
            if not reservations:
                return

            # Expand seats if needed
            self.seat_ui.expand_seats()

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