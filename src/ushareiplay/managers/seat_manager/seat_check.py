import asyncio
import traceback
from datetime import datetime, timedelta
from ushareiplay.dal import SeatReservationDAO, UserDAO
from ushareiplay.managers.seat_manager.base import SeatManagerBase
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager


class SeatCheckManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.seat_ui = SeatUIManager(handler)
        self._message_dispatch = None

    @property
    def message_dispatch(self):
        if self._message_dispatch is None:
            from ushareiplay.core.message_dispatch import MessageDispatch

            self._message_dispatch = MessageDispatch.instance().bind_handler(self.handler)
        return self._message_dispatch

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
        if not await self.seat_ui.expand_seats():
            self.handler.log_error("failed to expand seats for check")
            return
        await asyncio.sleep(0.5)  # wait for expansion animation

        # get all seat desks
        seat_desks = self.handler.find_elements('seat_desk')
        if not seat_desks:
            self.handler.log_error("cannot find seat desks")
            self.message_dispatch.send_screen_message(f"System error: Unable to access seats for {username}")
            return
        self.handler.logger.info(f"found {len(seat_desks)} seat desks")
        if len(seat_desks) != 6:
            self.handler.log_error(
                f"seat expansion incomplete: found {len(seat_desks)} desks, expected 6"
            )
            return

        # check and handle the user's specific seat
        self.handler.logger.info(f"checking specific seat {seat_number} for user {username}")

        desk_index = (seat_number - 1) // 2
        row_index = desk_index // 2
        if row_index in (0, 2):
            reference_desk = seat_desks[2]
            center_x = reference_desk.location['x'] + reference_desk.size['width'] // 2
            center_y = reference_desk.location['y'] + reference_desk.size['height'] // 2
            offset = reference_desk.size['height'] if row_index == 0 else -reference_desk.size['height']
            self.handler.driver.swipe(center_x, center_y, center_x, center_y + offset, 1000)
            await asyncio.sleep(0.5)

        await self._handle_occupied_seat(username, seat_desks, seat_number)

    async def _handle_occupied_seat(self, username: str, seat_desks, seat_number: int):
        """Handle an occupied seat by removing the occupant"""
        if self.handler is None:
            return

        # Determine if this is a left or right seat in the row
        is_left_seat = bool(seat_number % 2)
        desk_index = (seat_number - 1) // 2
        desk = seat_desks[desk_index]

        # Find the specific seat element
        if is_left_seat:
            seat_element = self.handler.find_child_element(desk, 'left_seat')
            seat_label = self.handler.find_child_element(seat_element, 'left_label')
        else:
            seat_element = self.handler.find_child_element(desk, 'right_seat')
            seat_label = self.handler.find_child_element(seat_element, 'right_label')

        if not seat_element:
            self.handler.logger.error(f"Cannot find seat element for seat {seat_number}")
            self.message_dispatch.send_screen_message(f"Failed to locate seat {seat_number} for {username}")
            return

        if not seat_label:
            self.handler.logger.warning(f"No occupant for seat {seat_number}")
            return
        self.handler.logger.info(f"Found seat {seat_number} with label {seat_label.text if seat_label else 'None'}")
        
        # Send welcome message only when seat is occupied to reduce message frequency
        self.message_dispatch.send_screen_message(f"Welcome {username}!")

        # wait for input dialog disappear
        await asyncio.sleep(1)
        # Click the specific seat element
        seat_element.click()
        self.handler.logger.info(f"Clicked seat {seat_number} to remove occupant")

        # Wait for seat off button
        seat_off = self.handler.wait_for_element_clickable('seat_off')
        if not seat_off:
            self.handler.logger.error(f"Failed to find seat off button for seat {seat_number}")
            self.message_dispatch.send_screen_message(f"Unable to manage seat {seat_number} for {username}")
            return

        found_key, souler_name = self.handler.wait_for_any_element(['souler_name', 'user_name'])
        if not souler_name:
            self.handler.logger.error(f"No souler name found for seat {seat_number}")
            self.message_dispatch.send_screen_message(f"Failed to verify occupant on seat {seat_number}")
            return

        souler_name_text = souler_name.text
        if souler_name_text == username:
            self.handler.logger.error(f"Souler {username} is already in seat {seat_number}")
            # No message needed - user is already seated successfully
            self.handler.press_back()
            return

        user = await UserDAO.get_by_username(username)
        souler = await UserDAO.get_by_username(souler_name_text)
        if user and souler and user.level <= souler.level:
            self.handler.logger.info(
                f"Souler {souler_name_text} has higher or equal level ({souler.level}) than {username} ({user.level}), skipping")
            self.handler.press_back()
            self.message_dispatch.send_screen_message(f"Cannot seat {username}: Seat {seat_number} occupied by higher level user")
            return

        seat_off.click()
        self.handler.logger.info(
            f"Successfully removed occupant {souler_name_text} from seat {seat_number} by {username}")
