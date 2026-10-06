import asyncio
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
import traceback


class SeatingManager(Singleton):
    def __init__(self, handler=None, seat_ui=None, observation=None):
        self.handler = handler
        self.seat_ui = seat_ui if seat_ui is not None else (SeatUIManager.instance() if SeatUIManager.is_initialized() else None)
        self._observation = observation
        self.current_desk_index = 0
        self.current_side = None

    @property
    def observation(self):
        if self._observation is not None:
            return self._observation
        from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
        if SeatObservationManager.is_initialized():
            return SeatObservationManager.instance()
        return None

    async def sit_at_specific_seat(self, seat_number: int) -> dict:
        """Sit at a specific seat position (1-12) with viewport sync and page-source verification."""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        if not 1 <= seat_number <= 12:
            return {'error': f'Invalid seat number {seat_number}. Must be between 1 and 12'}

        desk_index = (seat_number - 1) // 2
        row_index = desk_index // 2
        side = 'left' if seat_number % 2 == 1 else 'right'

        # 相位必须由本次真实滚动决定，不能只是声明：第二排（row 1）在展开后的
        # 默认可视区域内，但「默认视口就是顶相位」是没被真机证实过的假设 ——
        # 面板若停在滚动后的位置，带位偏移会算错。row 0/1 一律先滚到内容顶部
        # 夹住（row 1 时这次滚动被内容顶端夹住，是幂等的空操作），row 2 滚到底部。
        band = "bottom" if row_index == 2 else "top"
        scroll_target_desk = desk_index if row_index == 2 else 0

        try:
            # 展开座位面板
            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            # 直达目标行滚动，传播对应相位
            self.seat_ui.scroll_to_row(scroll_target_desk, seat_desks)
            await asyncio.sleep(0.3)

            # 视口同步与 DOM 证据校验
            obs = self.observation
            observed = await obs.sync_current_viewport(band=band)
            if not observed or seat_number not in observed:
                return {'error': f'Seat {seat_number} could not be verified in viewport'}

            desk, seat_side, info = observed[seat_number]
            if info.get('occupied'):
                occupied_label = info.get("label") or info.get("username") or "occupant"
                return {'error': f'Seat {seat_number} is already occupied by {occupied_label}'}
            if not info.get('is_empty'):
                # occupied=False 且 is_empty=False 是第三种状态：读不到判据（渲染缺证据）。
                # 它同样不该点击，但不能谎报成「有人占座」。
                return {'error': f'Seat {seat_number} could not be verified in viewport'}

            # 目标为空座，通过 page_source 导出的坐标点击
            seat_element = obs._find_child_element(desk, f"{side}_seat")
            seat_bounds = getattr(seat_element, "bounds", None) if seat_element else None
            if seat_bounds and seat_bounds.get("width") and seat_bounds.get("height"):
                click_x = seat_bounds["x"] + seat_bounds["width"] // 2
                click_y = seat_bounds["y"] + seat_bounds["height"] // 2
            else:
                desk_bounds = getattr(desk, "bounds", None) or obs._desk_bounds(desk)
                if not desk_bounds or not desk_bounds.get("width") or not desk_bounds.get("height"):
                    return {'error': f'Could not determine click bounds for seat {seat_number}'}
                w, h = desk_bounds["width"], desk_bounds["height"]
                click_x = desk_bounds["x"] + (w // 4 if side == "left" else (3 * w) // 4)
                click_y = desk_bounds["y"] + h // 2

            gesture = getattr(self.handler, "gesture_handler", None)
            if not gesture or not hasattr(gesture, "click_at"):
                # 点不了就必须报错返回：继续往下走会去等一个不存在的确认弹窗
                return {'error': f'Gesture handler cannot click; seat {seat_number} was not selected'}
            gesture.click_at(click_x, click_y)
            await asyncio.sleep(0.3)

            # 确认就座
            result = self._confirm_seat()
            if result.get('success'):
                obs.mark_owner_seated(seat_number)
                self.current_desk_index = desk_index
                self.current_side = side

            return result

        except Exception as e:
            if hasattr(self.handler, "log_error"):
                self.handler.log_error(f"Error sitting at specific seat: {traceback.format_exc()}")
            return {'error': f'Failed to sit at seat {seat_number}: {str(e)}'}
        finally:
            try:
                await self.seat_ui.collapse_seats()
            except Exception as e:
                if hasattr(self.handler, "logger") and self.handler.logger:
                    self.handler.logger.error(f"Failed to collapse seats: {e}")

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
            # Skip online check if sender is the target (they are obviously online).
            # 两侧名字可能来自不同命名域（调用方常拿到 DB 的主账号名，UI 只有分身名），
            # 所以同一身份必须按身份判定，而不是按字符串相等。
            from ushareiplay.dal.user_dao import UserDAO

            if not await UserDAO.is_same_identity(sender_username, target_username):
                info_manager = InfoManager.instance()
                if not await info_manager.is_user_or_avatar_online(target_username):
                    return {'error': f'User {target_username} is not online'}

            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            # Step 3: Iterate through all desks.
            # Optimization: only check desks with exactly one occupant, because
            # if both seats are occupied, we can't sit next to the target anyway.
            last_scrolled_row = -1
            for desk_index in range(len(seat_desks)):
                row_index = desk_index // 2
                if row_index != last_scrolled_row:
                    self.seat_ui.scroll_to_row(desk_index, seat_desks)
                    last_scrolled_row = row_index
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

                # 麦位弹窗里是 Soul UI 的可见名字（分身名），调用方给的可能是主账号名：
                # 按身份匹配，命中后一律使用 UI 可见名字继续后续动作。
                if not await UserDAO.is_same_identity(target_username, actual_username):
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
                    f"Sitting next to {actual_username} at desk {desk_index + 1}, {other_seat['side']} side"
                )

                # Re-collect desk info to get fresh element references after popup interaction
                desk_info = self._collect_desk_info(desk)
                fresh_other_seat = desk_info[other_side]

                return self._take_seat(
                    desk_index,
                    fresh_other_seat,
                    neighbor_label=actual_username
                )

            return {'error': f'User {target_username} not found on any seat'}

        except Exception as e:
            self.handler.log_error(f"Error accompanying user: {traceback.format_exc()}")
            return {'error': f'Failed to accompany user {target_username}: {str(e)}'}
        finally:
            if self.seat_ui and hasattr(self.seat_ui, "collapse_seats"):
                try:
                    await self.seat_ui.collapse_seats()
                except Exception as e:
                    if hasattr(self.handler, "logger") and self.handler.logger:
                        self.handler.logger.error(f"Failed to collapse seats: {e}")

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
