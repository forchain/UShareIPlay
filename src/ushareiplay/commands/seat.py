import traceback
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.seat_manager import SeatManager


class SeatCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = 'Failed to process seat command: {error}'

    def _is_guest_room(self) -> bool:
        try:
            from ushareiplay.state.room_state import RoomState
            return RoomState.instance().is_guest_room
        except Exception:
            return False

    async def process(self, message_info, parameters):
        try:
            return await super().process(message_info, parameters)
        finally:
            self._log_seating_layout()

    def _log_seating_layout(self):
        try:
            from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
            try:
                obs = SeatObservationManager.instance()
            except Exception:
                obs = None
            if not obs:
                return
            layout_str = obs.format_3row_layout(trigger_source="seat命令执行")
            logger = getattr(obs, "logger", None)
            if not logger and self.soul_handler:
                logger = getattr(self.soul_handler, "logger", None)
            if logger and hasattr(logger, "info"):
                logger.info(layout_str)
        except Exception as e:
            if self.soul_handler and hasattr(self.soul_handler, "log_error"):
                self.soul_handler.log_error(f"Error logging seat layout after seat command: {e}")

    async def _resolve_visible_username(self, nickname: str) -> str:
        """把昵称解析成 Soul UI 房间里可见的名字（分身名），解析不了则原样返回。"""
        if not nickname:
            return nickname
        try:
            return await self.info_manager.resolve_visible_username(nickname)
        except Exception:
            # 门面不可用时退回座位层的按身份匹配，不让解析失败变成命令失败。
            return nickname

    async def do_process(self, message_info, parameters):
        """Process seat command"""
        if self._is_guest_room():
            return {'error': '他人房间不支持座位功能'}

        if not parameters:
            # No parameters - find and take an available seat for owner
            return await SeatManager.get_instance().find_owner_seat(force_relocate=True)

        command = parameters[0]

        if command == '0':
            # Remove user's reservations
            return await SeatManager.get_instance().remove_user_reservation(message_info.nickname)
        elif command == '1' and len(parameters) == 2:
            # Reserve specific seat
            seat_number, err = self.coerce_int(
                parameters[1], 1, 12, 'Invalid seat number. Must be between 1 and 12')
            if err:
                return {'error': err}
            return await SeatManager.get_instance().reserve_seat(message_info.nickname, seat_number)
        elif command == '2' and len(parameters) == 2:
            # Sit at specific seat position
            seat_number, err = self.coerce_int(
                parameters[1], 1, 12, 'Invalid seat number. Must be between 1 and 12')
            if err:
                return {'error': err}
            return await SeatManager.get_instance().take_seat(seat_number)
        elif command == '3':
            # Accompany a specific user (sit next to them)
            # 座位层只认 Soul UI 上可见的名字（分身名）；调用方给的昵称、以及
            # 专注钩子带进来的 message_info.nickname，都可能是 DB 解析后的主账号名，
            # 所以先解析成房间里当前可见的那个名字，再交给座位层。
            target_username = (parameters[1].strip() if len(parameters) > 1 else message_info.nickname) or ''
            target_username = await self._resolve_visible_username(target_username)
            return await SeatManager.get_instance().accompany_user(target_username, sender_username=message_info.nickname)
        elif command == '4':
            if len(parameters) == 1:
                # Remove owner from their current seat
                return await SeatManager.get_instance().remove_seat_occupant(None)
            if len(parameters) == 2:
                # Remove whoever is sitting at the specified seat
                seat_number, err = self.coerce_int(
                    parameters[1], 1, 12, 'Invalid seat number. Must be between 1 and 12')
                if err:
                    return {'error': err}
                return await SeatManager.get_instance().remove_seat_occupant(seat_number)
            return {'error': 'Invalid command. Use: :seat 4 [seat_number]'}
        else:
            return {'error': 'Invalid command. Use: :seat [0|1 <seat_number>|2 <seat_number>|3 [username]|4 [seat_number]]'}

    async def user_enter(self, username: str):
        """Called when a user enters the party"""
        try:
            if self._is_guest_room():
                return
            # Check seats when user enters, passing the username
            await SeatManager.get_instance().check_seats_on_entry(username)
        except Exception as e:
            self.handler.log_error(f"Error checking seats on user enter: {traceback.format_exc()}")

    async def user_return(self, username: str):
        """Called when a user returns to the party"""
        try:
            if self._is_guest_room():
                return
            # Check seats when user returns, passing the username
            await SeatManager.get_instance().check_seats_on_entry(username)
        except Exception as e:
            self.handler.log_error(f"Error checking seats on user return: {traceback.format_exc()}")

    def update(self):
        """Update method - focus count monitoring has been migrated to event system"""
        # 专注数监控已迁移到事件系统，不再需要手动调用
        pass
