import time
import traceback
from datetime import datetime, timedelta
from ...dal import UserDAO, SeatReservationDAO
from ...models import User
from .base import SeatManagerBase
from .seat_ui import SeatUIManager


class SeatCheckManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.seat_ui = SeatUIManager(handler)

    async def check_seats_on_entry(self, username: str = None):
        """Check seats when user enters the party"""
        if self.handler is None or not username:
            return

        try:
            # Get user's reservation
            user_reservation = await SeatReservationDAO.get_reservation_by_user_name(username)
            if not user_reservation:
                return

            # Check if reservation is still valid
            now = datetime.now()

            # Ensure both datetimes are timezone-naive
            start_time = user_reservation.start_time
            if start_time.tzinfo is not None:
                # Convert to timezone-naive if needed
                from datetime import timezone
                start_time = start_time.replace(tzinfo=None)

            end_time = start_time + timedelta(hours=user_reservation.duration_hours)

            if now > end_time:
                # Reservation expired, remove it
                await SeatReservationDAO.remove_reservation(user_reservation)
                self.handler.logger.info(f"Removed expired reservation for user {username}")
                return

            # Reservation is valid, auto-renew it
            duration_hours = min(max(user_reservation.user.level, 1),
                                 24)  # Duration is user's level, between 1 and 24 hours
            await SeatReservationDAO.update_reservation_start_time(user_reservation.id, now)
            user_reservation.duration_hours = duration_hours
            await user_reservation.save()
            self.handler.logger.info(
                f"Auto-renewed reservation for user {username} with duration {duration_hours} hours")

            # Ensure seats are expanded first
            self.seat_ui.expand_seats()
            time.sleep(0.5)  # Wait for expansion animation

            # Get all seat desks
            seat_desks = self.handler.find_elements_plus('seat_desk')
            if not seat_desks:
                self.handler.log_error("Cannot find seat desks")
                return

            # Check and handle the user's specific seat
            await self._check_user_specific_seat(username, seat_desks)

        except Exception as e:
            self.handler.log_error(f"Error checking seats: {traceback.format_exc()}")

    async def _check_user_specific_seat(self, username: str, seat_desks):
        """Check and handle a specific user's seat"""
        if self.handler is None:
            return

        user_reservation = await SeatReservationDAO.get_reservation_by_user_name(username)
        if not user_reservation:
            return

        seat_number = user_reservation.seat_number
        row_index = (seat_number - 1) // 4  # 0-based row index

        # Handle row visibility based on index
        if row_index == 0 or row_index == 2:  # First or Third row
            # Use second row's desk (index 1) as reference for scrolling
            reference_desk = seat_desks[2]
            desk_height = reference_desk.size['height']

            if row_index == 0:  # First row
                # Scroll down one row height
                self.handler.driver.swipe(
                    reference_desk.location['x'] + reference_desk.size['width'] // 2,
                    reference_desk.location['y'] + reference_desk.size['height'] // 2,
                    reference_desk.location['x'] + reference_desk.size['width'] // 2,
                    reference_desk.location['y'] + reference_desk.size['height'] // 2 + desk_height,
                    1000
                )
            else:  # Third row
                # Scroll up one row height
                self.handler.driver.swipe(
                    reference_desk.location['x'] + reference_desk.size['width'] // 2,
                    reference_desk.location['y'] + reference_desk.size['height'] // 2,
                    reference_desk.location['x'] + reference_desk.size['width'] // 2,
                    reference_desk.location['y'] + reference_desk.size['height'] // 2 - desk_height,
                    1000
                )
            time.sleep(0.5)

        self._handle_occupied_seat(seat_desks, seat_number)

    def _handle_occupied_seat(self, seat_desks, seat_number: int):
        """Handle an occupied seat by removing the occupant"""
        if self.handler is None:
            return

        # Determine if this is a left or right seat in the row
        is_left_seat = bool(seat_number % 2)
        desk = seat_desks[int((seat_number - 1) / 2)]

        # Find the specific seat element
        if is_left_seat:
            seat_element = self.handler.find_child_element_plus(desk, 'left_seat')
            seat_label = self.handler.find_child_element_plus(seat_element, 'left_label')
        else:
            seat_element = self.handler.find_child_element_plus(desk, 'right_seat')
            seat_label = self.handler.find_child_element_plus(seat_element, 'right_label')

        if not seat_element:
            self.handler.logger.error(f"Cannot find seat element for seat {seat_number}")
            return

        if not seat_label:
            self.handler.logger.info(f"No occupant for seat {seat_number}")
            return
        self.handler.logger.info(f"Found seat {seat_number} with label {seat_label.text}")

        # Click the specific seat element
        seat_element.click()
        self.handler.logger.info(f"Clicked seat {seat_number} to remove occupant")

        # Wait for seat off button
        seat_off = self.handler.wait_for_element_clickable_plus('seat_off')
        if not seat_off:
            self.handler.logger.error(f"Failed to find seat off button for seat {seat_number}")
            return
        seat_off.click()
        self.handler.logger.info(f"Successfully removed occupant from seat {seat_number}")
