from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.seat_manager.desks import (
    OWNER_LABEL,
    adjacent_seat_number,
    desk_index_of,
    read_desk,
    seat_number_of,
    side_of,
)
from ushareiplay.managers.seat_manager.roster import UNKNOWN_USERNAME, SeatRoster
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
import traceback


class SeatingManager:
    def __init__(self, handler=None, seat_ui=None, probe=None, roster=None):
        self.handler = handler
        self.seat_ui = seat_ui or SeatUIManager(handler)
        self.probe = probe
        # Fall back to the probe's roster so both share one mapping by default.
        self.roster = roster or (probe.roster if probe is not None else SeatRoster())
        self.current_desk_index = 0
        self.current_side = None

    @property
    def room_owner(self) -> str:
        try:
            from ushareiplay.core.roles import RolePolicy

            return RolePolicy(getattr(self.handler, "config", None)).room_owner
        except Exception:
            return UNKNOWN_USERNAME

    async def sit_at_specific_seat(self, seat_number: int) -> dict:
        """Sit at a specific seat position (1-12)"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Odd numbers = left seat, Even numbers = right seat
            desk_index = desk_index_of(seat_number)
            side = side_of(seat_number)

            # The guard seat lets the sync reject an occupied target without
            # opening a single profile popup.
            seat_desks = await self.seat_ui.expand_and_find_desks(guard_seat=seat_number)
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            if desk_index >= len(seat_desks):
                return {'error': f'Desk {desk_index + 1} does not exist'}

            # Ensure the target row is visible
            self.seat_ui.scroll_to_row(desk_index, seat_desks)

            desk = seat_desks[desk_index]
            desk_info = self._collect_desk_info(desk)
            self._sense_desk(desk_index, desk_info)

            target_seat = desk_info[side]

            if target_seat['occupied']:
                occupant = self._occupant_name(seat_number, target_seat)
                return {'error': f'Seat {seat_number} is already occupied by {occupant}'}

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
                self._sense_desk(desk_index, desk_info)
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
                    self._sense_desk(first_empty_candidate['desk_index'], desk_info)
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
        """Sit next to a specific user.

        Expanding the panel already reconciled the Seat Roster with the on-screen
        occupancy, so the cached answer is normally correct and only needs one
        popup read to confirm the identity before taking the neighbouring seat.
        A failed confirmation re-probes every desk before reporting failure.
        """
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Skip online check if sender is the target (they are obviously online)
            if sender_username != target_username:
                info_manager = InfoManager.instance()
                if not info_manager.is_user_online(target_username):
                    return {'error': f'User {target_username} is not online'}

            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            seat_number = await self._locate_target_seat(seat_desks, target_username)
            if seat_number is None:
                return {'error': f'User {target_username} not found on any seat'}

            neighbour = adjacent_seat_number(seat_number)
            if self.roster.is_occupied(neighbour):
                return {'error': f'User {target_username} has no empty adjacent seat'}

            desk_index = desk_index_of(neighbour)
            self.seat_ui.scroll_to_row(desk_index, seat_desks)
            desk_info = self._collect_desk_info(seat_desks[desk_index])
            self._sense_desk(desk_index, desk_info)

            # Re-check against the fresh read: somebody may have taken the seat
            # while we were reading the target's profile.
            neighbour_seat = desk_info[side_of(neighbour)]
            if neighbour_seat['occupied']:
                return {'error': f'User {target_username} has no empty adjacent seat'}

            self.handler.logger.info(
                f"Sitting next to {target_username} at desk {desk_index + 1}, "
                f"{side_of(neighbour)} side"
            )
            return self._take_seat(
                desk_index,
                neighbour_seat,
                neighbor_label=target_username
            )

        except Exception as e:
            self.handler.log_error(f"Error accompanying user: {traceback.format_exc()}")
            return {'error': f'Failed to accompany user {target_username}: {str(e)}'}

    async def _locate_target_seat(self, seat_desks, target_username):
        """Resolve the target's seat, confirming a cached answer with one popup."""
        cached_seat = self.roster.find_seat_of(target_username)
        if cached_seat is not None:
            if await self._confirm_seat_occupant(seat_desks, cached_seat, target_username):
                return cached_seat
            # The popup contradicted the cache: force a full differential probe
            # before concluding the target is not seated at all.
            self.roster.invalidate(cached_seat)

        await self._resync_roster(seat_desks)
        return self.roster.find_seat_of(target_username)

    async def _confirm_seat_occupant(self, seat_desks, seat_number, expected_username) -> bool:
        """Check one seat's occupant identity, at the cost of a single popup."""
        if self.probe is None:
            return False

        desk_index = desk_index_of(seat_number)
        self.seat_ui.scroll_to_row(desk_index, seat_desks)
        desk_info = self._collect_desk_info(seat_desks[desk_index])
        self._sense_desk(desk_index, desk_info)

        entry = desk_info[side_of(seat_number)]
        if not entry.get('occupied'):
            return False
        return self.probe.identify_seat(seat_number, entry) == expected_username

    async def _resync_roster(self, seat_desks) -> None:
        """Force the differential probe to reconcile every readable desk."""
        if self.probe is None:
            return
        await self.probe.sync(seat_desks)

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
                self._sense_desk(desk_index, desk_info)

                for seat in (desk_info['left'], desk_info['right']):
                    if seat.get('is_owner') and seat.get('occupied'):
                        seat_number = seat_number_of(desk_index, seat['side'])
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
            desk_index = desk_index_of(seat_number)
            side = side_of(seat_number)

            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            if desk_index >= len(seat_desks):
                return {'error': f'Desk {desk_index + 1} does not exist'}

            self.seat_ui.scroll_to_row(desk_index, seat_desks)
            desk = seat_desks[desk_index]
            desk_info = self._collect_desk_info(desk)
            self._sense_desk(desk_index, desk_info)
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
        return read_desk(self.handler, desk)

    def _sense_desk(self, desk_index: int, desk_info) -> None:
        """Fold a just-scrolled row into the roster.

        Reading a row we already scrolled to is free, so seats passing through
        the viewport are cleared or flagged without any extra UI pass.
        """
        if self.probe is None:
            return
        self.probe.observe_desk(desk_index, desk_info)

    def _occupant_name(self, seat_number: int, seat_info) -> str:
        """Best name we can give for an occupied seat, without opening a popup."""
        occupant = self.roster.occupant(seat_number)
        if occupant is not None and occupant.verified and occupant.username != UNKNOWN_USERNAME:
            return occupant.username
        if seat_info.get('is_owner'):
            return OWNER_LABEL
        return UNKNOWN_USERNAME

    def _record_self_seated(self, seat_number: int) -> None:
        """Our own confirmed action tells us exactly where we are; no probe needed."""
        owner = self.room_owner
        previous_seat = self.roster.find_seat_of(owner)
        if previous_seat is not None and previous_seat != seat_number:
            self.roster.clear_seat(previous_seat)
            self.roster.note_occupancy(previous_seat, False)
        self.roster.set_occupant(seat_number, owner, is_owner=True, verified=True)
        self.roster.note_occupancy(seat_number, True)

    def _record_self_unseated(self, seat_number: int) -> None:
        """Mirror a confirmed removal so the roster needs no follow-up probe."""
        seat = self.roster.clear_seat(seat_number)
        if seat is not None:
            self.roster.note_occupancy(seat_number, False)

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
                self._record_self_seated(seat_number_of(desk_index, seat_info['side']))
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
            self._record_self_unseated(seat_number)
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
