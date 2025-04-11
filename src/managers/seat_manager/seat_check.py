import time
import traceback
from datetime import datetime, timedelta
from ...dal import SeatReservationDAO, UserDAO
from .base import SeatManagerBase
from .seat_ui import SeatUIManager


class SeatCheckManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.seat_ui = SeatUIManager(handler)

    async def check_seats_on_entry(self, username: str = None):
        """Check seats when user enters the party"""
        if self.handler is None or not username:
            self.handler.logger.warning("check_seats_on_entry called with invalid parameters")
            return

        try:
            self.handler.logger.info(f"Starting seat check for user {username}")

            # Get user's reservation
            user_reservation = await SeatReservationDAO.get_reservation_by_user_name(username)
            if not user_reservation:
                self.handler.logger.info(f"No reservation found for user {username}")
                return

            self.handler.logger.info(f"Found reservation for user {username} on seat {user_reservation.seat_number}")

            # Check if reservation is still valid
            now = datetime.now()
            self.handler.logger.info(f"Current time: {now}")

            # Ensure both datetimes are timezone-naive
            start_time = user_reservation.start_time
            if start_time.tzinfo is not None:
                # Convert to timezone-naive if needed
                from datetime import timezone
                start_time = start_time.replace(tzinfo=None)
                self.handler.logger.info(f"Converted start_time to timezone-naive: {start_time}")

            end_time = start_time + timedelta(hours=user_reservation.duration_hours)
            self.handler.logger.info(f"Reservation period: {start_time} to {end_time}")

            if now > end_time:
                # Reservation expired, remove it
                self.handler.logger.info(f"Reservation for user {username} has expired, removing it")
                await SeatReservationDAO.remove_reservation(user_reservation)
                self.handler.logger.info(f"Successfully removed expired reservation for user {username}")
                return

            # Reservation is valid, auto-renew it
            duration_hours = min(max(user_reservation.user.level, 1),
                                 24)  # Duration is user's level, between 1 and 24 hours
            self.handler.logger.info(
                f"Auto-renewing reservation for user {username} (level {user_reservation.user.level}) with duration {duration_hours} hours")

            await SeatReservationDAO.update_reservation_start_time(user_reservation.id, now)
            self.handler.logger.info(f"Successfully auto-renewed reservation for user {username}")

            user_reservation = await SeatReservationDAO.get_reservation_by_user_name(username)
            if not user_reservation:
                return

            await self.check_user_specific_seat(username, user_reservation.seat_number)

        except Exception as e:
            self.handler.log_error(f"Error checking seats: {traceback.format_exc()}")

    async def check_user_specific_seat(self, username: str, seat_number: int):
        # ensure seats are expanded first
        self.handler.logger.info("expanding seats for check")
        self.seat_ui.expand_seats()
        time.sleep(0.5)  # wait for expansion animation
        self.handler.logger.info("seats expanded successfully")

        # get all seat desks
        seat_desks = self.handler.find_elements_plus('seat_desk')
        if not seat_desks:
            self.handler.log_error("cannot find seat desks")
            return
        self.handler.logger.info(f"found {len(seat_desks)} seat desks")

        # check and handle the user's specific seat
        self.handler.logger.info(f"checking specific seat {seat_number} for user {username}")

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

        await self._handle_occupied_seat(username, seat_desks, seat_number)

    async def _handle_occupied_seat(self, username: str, seat_desks, seat_number: int):
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
            self.handler.logger.warning(f"No occupant for seat {seat_number}")
        self.handler.logger.info(f"Found seat {seat_number} with label {seat_label.text if seat_label else 'None'}")

        # Click the specific seat element
        seat_element.click()
        self.handler.logger.info(f"Clicked seat {seat_number} to remove occupant")

        souler_name = self.handler.wait_for_element_plus('souler_name')
        if not souler_name:
            souler_name = self.handler.wait_for_element_plus('user_name')
            if not souler_name:
                self.handler.logger.error(f"No souler name found for seat {seat_number}")
                return

        souler_name_text = souler_name.text 
        if souler_name_text == username:
            self.handler.logger.error(f"Souler {username} is already in seat {seat_number}")
            return

        user = await UserDAO.get_by_username(username)
        souler = await UserDAO.get_by_username(souler_name_text)
        if user and souler and user.level <= souler.level:
            self.handler.logger.info(f"Souler {souler_name_text} does not have higher level ({souler.level}) than {username} ({user.level}), skipping")
            return

        # Wait for seat off button
        seat_off = self.handler.wait_for_element_clickable_plus('seat_off')
        if not seat_off:
            self.handler.logger.error(f"Failed to find seat off button for seat {seat_number}")
            return

        souler_name = self.handler.try_find_element_plus('souler_name')
        if not souler_name:
            souler_name = self.handler.try_find_element_plus('user_name')
        if not souler_name:
            self.handler.logger.error(f"No souler name found for seat {seat_number}")
            return

        souler_name_text = souler_name.text
        if souler_name_text == username:
            self.handler.logger.error(f"Souler {username} is already in seat {seat_number}")
            return

        seat_off.click()
        self.handler.logger.info(
            f"Successfully removed occupant {souler_name_text} from seat {seat_number} by {username}")
