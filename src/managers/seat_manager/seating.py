from .base import SeatManagerBase
from .seat_ui import SeatUIManager
import time
import traceback


class SeatingManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.seat_ui = SeatUIManager(handler)

    def _check_owner_seated(self, desk, seat_desks) -> dict:
        """Check if owner is already seated in the desk
        Args:
            desk: The desk to check
            seat_desks: List of all desks for index calculation
        Returns:
            dict: Success if owner is seated, None otherwise
        """
        left_label = self.handler.find_child_element_plus(desk, 'left_label')
        right_label = self.handler.find_child_element_plus(desk, 'right_label')
        
        left_text = left_label.text if left_label else 'None'
        right_text = right_label.text if right_label else 'None'
        
        if (left_text == '群主') or (right_text == '群主'):
            desk_index = seat_desks.index(desk)
            self.handler.logger.info(f"Owner is already seated at desk {desk_index + 1}, {'left' if left_text == '群主' else 'right'} side")
            return {'success': 'Owner is already seated'}
            
        return None

    def find_owner_seat(self) -> dict:
        """Find and take an available seat for owner"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Expand seats if needed
            self.seat_ui.expand_seats()
            time.sleep(0.5)  # Wait for expansion animation

            # Find all seat desks
            seat_desks = self.handler.find_elements_plus('seat_desk')
            if not seat_desks:
                self.handler.logger.error("Failed to find seat desks")
                return {'error': 'Failed to find seat desks'}

            # Try to find a seat next to someone
            for desk in seat_desks:
                result = self._try_find_seat_next_to_someone(desk)
                if result:
                    return result

            # Check if owner is already seated before trying any available seat
            for desk in seat_desks:
                result = self._check_owner_seated(desk, seat_desks)
                if result:
                    return result

            # If no seats next to someone found and owner is not seated, try any available seat
            for desk in seat_desks:
                result = self._try_find_any_available_seat(desk)
                if result:
                    return result

            return {'error': 'No available seats found'}

        except Exception as e:
            self.handler.log_error(f"Error finding seat: {traceback.format_exc()}")
            return {'error': f'Failed to find seat: {str(e)}'}

    def _try_find_seat_next_to_someone(self, desk) -> dict:
        """Try to find a seat next to someone in the container"""
        if self.handler is None:
            return None

        # Check both seats in this container
        left_state = self.handler.find_child_element_plus(desk, 'left_state')
        right_state = self.handler.find_child_element_plus(desk, 'right_state')
        left_label = self.handler.find_child_element_plus(desk, 'left_label')
        right_label = self.handler.find_child_element_plus(desk, 'right_label')

        # If owner is in left seat and right seat has someone
        if left_label and left_label.text == '群主' and right_state:
            neighbor_label = right_label.text if right_label else 'Unknown'
            self.handler.logger.info(f"Owner is in left seat and already has {neighbor_label} in right seat, skipping")
            return {'success': f'Owner is in left seat and already has {neighbor_label} in right seat'}
            
        # If owner is in right seat and left seat has someone
        if right_label and right_label.text == '群主' and left_state:
            neighbor_label = left_label.text if left_label else 'Unknown'
            self.handler.logger.info(f"Owner is in right seat and already has {neighbor_label} in left seat, skipping")
            return {'success': f'Owner is in right seat and already has {neighbor_label} in left seat'}

        # If left seat is empty and right seat has someone
        if not left_state and right_state and (not right_label or right_label.text != '群主'):
            left_seat = self.handler.find_child_element_plus(desk, 'left_seat')
            if left_seat:
                left_seat.click()
                self.handler.logger.info("Clicked left seat next to occupied right seat")
                return self._confirm_seat()

        # If right seat is empty and left seat has someone
        if not right_state and left_state and (not left_label or left_label.text != '群主'):
            right_seat = self.handler.find_child_element_plus(desk, 'right_seat')
            if right_seat:
                right_seat.click()
                self.handler.logger.info("Clicked right seat next to occupied left seat")
                return self._confirm_seat()

        return None

    def _try_find_any_available_seat(self, container) -> dict:
        """Try to find any available seat in the container"""
        if self.handler is None:
            return None

        left_seat = self.handler.find_child_element_plus(container, 'left_seat')
        left_state = self.handler.find_child_element_plus(container, 'left_state')
        if left_seat and not left_state:
            left_seat.click()
            self.handler.logger.info("Clicked available left seat")
            return self._confirm_seat()

        right_seat = self.handler.find_child_element_plus(container, 'right_seat')
        right_state = self.handler.find_child_element_plus(container, 'right_state')
        if right_seat and not right_state:
            right_seat.click()
            self.handler.logger.info("Clicked available right seat")
            return self._confirm_seat()

        return None

    def _confirm_seat(self) -> dict:
        """Confirm seat selection"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Wait for confirmation dialog
            confirm_button = self.handler.wait_for_element_clickable_plus('confirm_seat')
            if not confirm_button:
                self.handler.logger.error("Failed to find confirm button")
                return {'error': 'Failed to find confirm button'}

            confirm_button.click()
            self.handler.logger.info("Confirmed seat selection")
            bottom_drawer = self.handler.wait_for_element_clickable_plus('bottom_drawer')
            if bottom_drawer:
                self.handler.click_element_at(bottom_drawer, 0.5, -0.1)
                self.handler.logger.info("Hide bottom drawer")
            return {'success': 'Successfully took a seat'}

        except Exception as e:
            self.handler.log_error(f"Error confirming seat: {traceback.format_exc()}")
            return {'error': f'Failed to confirm seat: {str(e)}'}
