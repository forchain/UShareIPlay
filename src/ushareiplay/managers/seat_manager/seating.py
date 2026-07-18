import asyncio
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
import traceback


class SeatingManager:
    def __init__(self, handler=None, seat_ui=None):
        self.handler = handler
        self.seat_ui = seat_ui or SeatUIManager(handler)
        self.current_desk_index = 0
        self.current_side = None

    async def sit_at_specific_seat(self, seat_number: int) -> dict:
        """Sit at a specific seat position (1-12)"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Convert seat number to desk index and side
            # Odd numbers = left seat, Even numbers = right seat
            desk_index = (seat_number - 1) // 2
            side = 'left' if seat_number % 2 == 1 else 'right'

            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            if desk_index >= len(seat_desks):
                return {'error': f'Desk {desk_index + 1} does not exist'}

            # Ensure the target row is visible
            self.seat_ui.scroll_to_row(desk_index, seat_desks)

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

    async def find_owner_seat(self, force_relocate: bool = False) -> dict:
        """Find and take an available seat for owner"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
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
                self.seat_ui.scroll_to_row(desk_index, seat_desks)
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
                # Ensure the row containing the target seat is visible before taking it
                # This is important because we may have scrolled to other rows during scanning
                try:
                    self.seat_ui.scroll_to_row(first_empty_candidate['desk_index'], seat_desks)
                    # Re-collect desk info to get fresh element references after scrolling
                    desk = seat_desks[first_empty_candidate['desk_index']]
                    desk_info = self._collect_desk_info(desk)
                    # Update the seat element reference to ensure it's still valid
                    side = first_empty_candidate['seat']['side']
                    if side in desk_info and desk_info[side].get('element'):
                        first_empty_candidate['seat'] = desk_info[side]
                except Exception as e:
                    # If refreshing fails, log but continue with original candidate
                    self.handler.logger.warning(f"Failed to refresh seat element before taking seat: {str(e)}")

                return self._take_seat(
                    first_empty_candidate['desk_index'],
                    first_empty_candidate['seat']
                )

            return {'error': 'No available seats found'}

        except Exception as e:
            self.handler.log_error(f"Error finding seat: {traceback.format_exc()}")
            return {'error': f'Failed to find seat: {str(e)}'}

    async def accompany_user(self, target_username: str, sender_username: str = None) -> dict:
        """Find a specific user on seats and sit next to them"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Step 1: Check if the target user is online
            # Skip online check if sender is the target (they are obviously online)
            if sender_username != target_username:
                info_manager = InfoManager.instance()
                if not info_manager.is_user_online(target_username):
                    return {'error': f'User {target_username} is not online'}

            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            # Step 3: Iterate through all desks.
            # Optimization: only check desks with exactly one occupant, because
            # if both seats are occupied, we can't sit next to the target anyway.
            for desk_index in range(len(seat_desks)):
                self.seat_ui.scroll_to_row(desk_index, seat_desks)
                desk = seat_desks[desk_index]
                desk_info = self._collect_desk_info(desk)

                left = desk_info['left']
                right = desk_info['right']
                occupied_sides = []
                if left.get('occupied'):
                    occupied_sides.append('left')
                if right.get('occupied'):
                    occupied_sides.append('right')

                # Only proceed when exactly one seat is occupied on this desk
                if len(occupied_sides) != 1:
                    continue

                side = occupied_sides[0]
                other_side = 'right' if side == 'left' else 'left'
                seat = desk_info[side]
                other_seat = desk_info[other_side]

                # Skip owner seat
                if seat.get('is_owner'):
                    continue

                # Click the state element to open user profile popup
                state_key = f'{side}_state'
                state_element = self.handler.element_finder.find_child_element(
                    desk, state_key, log_failure=False
                )
                if not state_element:
                    continue

                state_element.click()
                self.handler.logger.info(f"Clicked {side} seat at desk {desk_index + 1} to check user")

                # Read the user name from the popup
                found_key, name_element = self.handler.element_finder.wait_for_any_element(
                    ['souler_name', 'user_name']
                )
                if not name_element:
                    self.handler.logger.warning(f"No user name found for {side} seat at desk {desk_index + 1}")
                    self.handler.key_actions.press_back()
                    continue

                actual_username = name_element.text
                self.handler.logger.info(
                    f"Found user '{actual_username}' at desk {desk_index + 1}, {side} side"
                )

                if actual_username != target_username:
                    # Not the target user, close popup and continue
                    self.handler.key_actions.press_back()
                    await asyncio.sleep(0.3)
                    continue

                # Found the target user! Close the popup first
                self.handler.key_actions.press_back()
                await asyncio.sleep(0.3)

                # Check if the adjacent seat is available
                if other_seat['occupied']:
                    return {'error': f'User {target_username} has no empty adjacent seat'}

                # Sit next to the target user
                self.handler.logger.info(
                    f"Sitting next to {target_username} at desk {desk_index + 1}, {other_seat['side']} side"
                )

                # Re-collect desk info to get fresh element references after popup interaction
                desk_info = self._collect_desk_info(desk)
                fresh_other_seat = desk_info[other_side]

                return self._take_seat(
                    desk_index,
                    fresh_other_seat,
                    neighbor_label=target_username
                )

            return {'error': f'User {target_username} not found on any seat'}

        except Exception as e:
            self.handler.log_error(f"Error accompanying user: {traceback.format_exc()}")
            return {'error': f'Failed to accompany user {target_username}: {str(e)}'}

    async def seat_off_owner(self) -> dict:
        """Remove the owner from their current seat."""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            for desk_index in range(len(seat_desks)):
                self.seat_ui.scroll_to_row(desk_index, seat_desks)
                desk = seat_desks[desk_index]
                desk_info = self._collect_desk_info(desk)

                for seat in (desk_info['left'], desk_info['right']):
                    if seat.get('is_owner') and seat.get('occupied'):
                        seat_number = desk_index * 2 + (1 if seat['side'] == 'left' else 2)
                        return self._seat_off(seat_number, seat)

            self.handler.logger.warning("Owner is not on any seat")
            return {'error': 'Owner is not on any seat'}

        except Exception as e:
            self.handler.log_error(f"Error removing owner from seat: {traceback.format_exc()}")
            return {'error': f'Failed to remove owner from seat: {str(e)}'}

    async def seat_off_specific_seat(self, seat_number: int) -> dict:
        """Remove the occupant from a specific seat position (1-12)."""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            desk_index = (seat_number - 1) // 2
            side = 'left' if seat_number % 2 == 1 else 'right'

            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            if desk_index >= len(seat_desks):
                return {'error': f'Desk {desk_index + 1} does not exist'}

            self.seat_ui.scroll_to_row(desk_index, seat_desks)
            desk = seat_desks[desk_index]
            desk_info = self._collect_desk_info(desk)
            target_seat = desk_info[side]

            if not target_seat.get('occupied'):
                return {'error': f'Seat {seat_number} is empty'}

            return self._seat_off(seat_number, target_seat)

        except Exception as e:
            self.handler.log_error(f"Error removing seat occupant: {traceback.format_exc()}")
            return {'error': f'Failed to remove occupant from seat {seat_number}: {str(e)}'}

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
        left_seat = self.handler.element_finder.find_child_element(desk, 'left_seat', log_failure=False)
        right_seat = self.handler.element_finder.find_child_element(desk, 'right_seat', log_failure=False)
        left_state = self.handler.element_finder.find_child_element(desk, 'left_state', log_failure=False)
        right_state = self.handler.element_finder.find_child_element(desk, 'right_state', log_failure=False)
        left_label_element = self.handler.element_finder.find_child_element(desk, 'left_label', log_failure=False)
        right_label_element = self.handler.element_finder.find_child_element(desk, 'right_label', log_failure=False)

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

    def _seat_off(self, seat_number, seat_info):
        if self.handler is None or not seat_info or not seat_info.get('element'):
            return {'error': 'Seat element not available'}

        try:
            seat_info['element'].click()
            self.handler.logger.info(f"Clicked seat {seat_number} to remove occupant")

            seat_off = self.handler.element_finder.wait_for_element_clickable('seat_off')
            if not seat_off:
                self.handler.logger.error(f"Failed to find seat off button for seat {seat_number}")
                return {'error': f'Unable to manage seat {seat_number}'}

            found_key, souler_name = self.handler.element_finder.wait_for_any_element(['souler_name', 'user_name'])
            if not souler_name:
                self.handler.logger.error(f"No souler name found for seat {seat_number}")
                return {'error': f'Failed to verify occupant on seat {seat_number}'}

            souler_name_text = souler_name.text
            seat_off.click()
            self.handler.logger.info(f"Successfully removed {souler_name_text} from seat {seat_number}")
            return {'success': f'Successfully removed {souler_name_text} from seat {seat_number}'}

        except Exception:
            self.handler.log_error(f"Error while removing seat occupant: {traceback.format_exc()}")
            return {'error': 'Failed to remove seat occupant'}

    def _confirm_seat(self) -> dict:
        """Confirm seat selection"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Wait for confirmation dialog
            confirm_button = self.handler.element_finder.wait_for_element_clickable('confirm_seat')
            if not confirm_button:
                self.handler.logger.error("Failed to find confirm button")
                return {'error': 'Failed to find confirm button'}

            confirm_button.click()
            self.handler.logger.info("Confirmed seat selection")
            bottom_drawer = self.handler.element_finder.wait_for_element_clickable('bottom_drawer')
            if bottom_drawer:
                self.handler.gesture_handler.click_element_at(bottom_drawer, 0.5, -0.1)
                self.handler.logger.info("Hide bottom drawer")
            return {'success': 'Successfully took a seat'}

        except Exception as e:
            self.handler.log_error(f"Error confirming seat: {traceback.format_exc()}")
            return {'error': f'Failed to confirm seat: {str(e)}'}
