from .base import SeatManagerBase
from .seat_ui import SeatUIManager
import time
import traceback


class SeatingManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        if not hasattr(self, 'seat_ui'):
            self.seat_ui = SeatUIManager(handler)
        elif handler and self.seat_ui.handler is None:
            self.seat_ui.handler = handler

        if not hasattr(self, 'current_desk_index'):
            self.current_desk_index = 0
        if not hasattr(self, 'current_side'):
            self.current_side = None

    def sit_at_specific_seat(self, seat_number: int) -> dict:
        """Sit at a specific seat position (1-12)"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Convert seat number to desk index and side
            # Odd numbers = left seat, Even numbers = right seat
            desk_index = (seat_number - 1) // 2
            side = 'left' if seat_number % 2 == 1 else 'right'

            # Expand seats if needed
            self.seat_ui.expand_seats()
            time.sleep(0.5)  # Wait for expansion animation

            # Find all seat desks
            seat_desks = self.handler.find_elements_plus('seat_desk')
            if not seat_desks:
                self.handler.logger.error("Failed to find seat desks")
                return {'error': 'Failed to find seat desks'}

            if desk_index >= len(seat_desks):
                return {'error': f'Desk {desk_index + 1} does not exist'}

            # Ensure the target row is visible
            self._ensure_row_visible(desk_index, seat_desks)

            # Get the specific desk and collect its info
            desk = seat_desks[desk_index]
            desk_info = self._collect_desk_info(desk)

            # Get the target seat info
            target_seat = desk_info[side]

            # Check if the target seat is occupied
            if target_seat['occupied']:
                return {'error': f'Seat {seat_number} is already occupied by {target_seat["label"]}'}

            # Take the seat
            self.handler.logger.info(f"Sitting at seat {seat_number} (desk {desk_index + 1}, {side} side)")
            return self._take_seat(desk_index, target_seat)

        except Exception as e:
            self.handler.log_error(f"Error sitting at specific seat: {traceback.format_exc()}")
            return {'error': f'Failed to sit at seat {seat_number}: {str(e)}'}

    def find_owner_seat(self, force_relocate: bool = False) -> dict:
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

            if self.current_desk_index >= len(seat_desks):
                self.current_desk_index = 0

            owner_position = self._get_owner_position(seat_desks)
            if owner_position:
                self.current_desk_index = owner_position['desk_index']
                self.current_side = owner_position['side']

                if owner_position['has_neighbor'] and not force_relocate:
                    self.handler.logger.info(
                        f"Owner already accompanying {owner_position['neighbor_label']} at desk {owner_position['desk_index'] + 1}"
                    )
                    return {'success': 'Owner already has a companion'}

            start_index = self.current_desk_index
            if owner_position:
                start_index = (owner_position['desk_index'] + 1) % len(seat_desks)

            scan_order = self._build_scan_order(len(seat_desks), start_index)
            first_empty_candidate = None

            for desk_index in scan_order:
                # Ensure the row containing this desk is visible
                self._ensure_row_visible(desk_index, seat_desks)
                desk = seat_desks[desk_index]
                desk_info = self._collect_desk_info(desk)
                # self.handler.logger.debug(f"desk_info: {desk_info}" )

                companion_candidate = self._select_companion_candidate(desk_info)
                if companion_candidate:
                    return self._take_seat(
                        desk_index,
                        companion_candidate['seat'],
                        neighbor_label=companion_candidate['neighbor_label']
                    )

                if not first_empty_candidate:
                    empty_candidate = self._select_empty_candidate(desk_info)
                    if empty_candidate:
                        first_empty_candidate = {
                            'desk_index': desk_index,
                            'seat': empty_candidate
                        }

            if first_empty_candidate:
                return self._take_seat(
                    first_empty_candidate['desk_index'],
                    first_empty_candidate['seat']
                )

            return {'error': 'No available seats found'}

        except Exception as e:
            self.handler.log_error(f"Error finding seat: {traceback.format_exc()}")
            return {'error': f'Failed to find seat: {str(e)}'}

    def _get_owner_position(self, seat_desks):
        for index, desk in enumerate(seat_desks):
            desk_info = self._collect_desk_info(desk)
            left = desk_info['left']
            right = desk_info['right']

            if left['is_owner']:
                has_neighbor = right['occupied'] and not right['is_owner']
                return {
                    'desk_index': index,
                    'side': 'left',
                    'has_neighbor': has_neighbor,
                    'neighbor_label': right['label'] if has_neighbor else ''
                }

            if right['is_owner']:
                has_neighbor = left['occupied'] and not left['is_owner']
                return {
                    'desk_index': index,
                    'side': 'right',
                    'has_neighbor': has_neighbor,
                    'neighbor_label': left['label'] if has_neighbor else ''
                }

        return None

    def _collect_desk_info(self, desk):
        left_seat = self.handler.find_child_element_plus(desk, 'left_seat')
        right_seat = self.handler.find_child_element_plus(desk, 'right_seat')
        left_state = self.handler.find_child_element_plus(desk, 'left_state')
        right_state = self.handler.find_child_element_plus(desk, 'right_state')
        left_label_element = self.handler.find_child_element_plus(desk, 'left_label')
        right_label_element = self.handler.find_child_element_plus(desk, 'right_label')

        left_label = left_label_element.text if left_label_element else ''
        right_label = right_label_element.text if right_label_element else ''

        return {
            'left': {
                'element': left_seat,
                'occupied': bool(left_state),
                'label': left_label,
                'is_owner': left_label == '群主',
                'side': 'left'
            },
            'right': {
                'element': right_seat,
                'occupied': bool(right_state),
                'label': right_label,
                'is_owner': right_label == '群主',
                'side': 'right'
            }
        }

    def _select_companion_candidate(self, desk_info):
        left = desk_info['left']
        right = desk_info['right']

        if right['element'] and left['occupied'] and not left['is_owner'] and not right['occupied']:
            return {'seat': right, 'neighbor_label': left['label'] or 'Unknown'}

        if left['element'] and right['occupied'] and not right['is_owner'] and not left['occupied']:
            return {'seat': left, 'neighbor_label': right['label'] or 'Unknown'}

        return None

    def _select_empty_candidate(self, desk_info):
        for seat in (desk_info['left'], desk_info['right']):
            if seat['element'] and not seat['occupied'] and not seat['is_owner']:
                return seat
        return None

    def _build_scan_order(self, total_count, start_index):
        return [(start_index + offset) % total_count for offset in range(total_count)]

    def _ensure_row_visible(self, desk_index, seat_desks):
        """Ensure the row containing the desk is visible by scrolling if needed"""
        if not seat_desks or len(seat_desks) < 3:
            return
        
        # Calculate which row the desk belongs to (row_index = desk_index // 2)
        row_index = desk_index // 2
        
        # Row 1 (desk_index 2-3) is always visible, no scrolling needed
        if row_index == 1:
            return
        
        # Use second row's first desk (index 2) as reference for scrolling
        reference_desk = seat_desks[2]
        desk_height = reference_desk.size['height']
        
        if row_index == 0:  # First row (desk_index 0-1)
            # Scroll down one row height to show first row
            self.handler.driver.swipe(
                reference_desk.location['x'] + reference_desk.size['width'] // 2,
                reference_desk.location['y'] + reference_desk.size['height'] // 2,
                reference_desk.location['x'] + reference_desk.size['width'] // 2,
                reference_desk.location['y'] + reference_desk.size['height'] // 2 + desk_height,
                1000
            )
            time.sleep(0.5)  # Wait for scroll animation
            self.handler.logger.info(f"Scrolled to show first row for desk {desk_index}")
        elif row_index == 2:  # Third row (desk_index 4-5)
            # Scroll up one row height to show third row
            self.handler.driver.swipe(
                reference_desk.location['x'] + reference_desk.size['width'] // 2,
                reference_desk.location['y'] + reference_desk.size['height'] // 2,
                reference_desk.location['x'] + reference_desk.size['width'] // 2,
                reference_desk.location['y'] + reference_desk.size['height'] // 2 - desk_height,
                1000
            )
            time.sleep(0.5)  # Wait for scroll animation
            self.handler.logger.info(f"Scrolled to show third row for desk {desk_index}")

    def _take_seat(self, desk_index, seat_info, neighbor_label=None):
        if self.handler is None or not seat_info or not seat_info.get('element'):
            return {'error': 'Seat element not available'}

        try:
            seat_info['element'].click()
            if neighbor_label:
                self.handler.logger.info(
                    f"Accompanying {neighbor_label} at desk {desk_index + 1}, {seat_info['side']} seat"
                )
            else:
                self.handler.logger.info(
                    f"Taking empty {seat_info['side']} seat at desk {desk_index + 1}"
                )

            result = self._confirm_seat()
            if result.get('success'):
                self.current_desk_index = desk_index
                self.current_side = seat_info['side']
            return result

        except Exception:
            self.handler.log_error(f"Error while clicking seat: {traceback.format_exc()}")
            return {'error': 'Failed to click seat'}

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
