"""`:seat` 入站适配器：解析参数并委派给 `SeatService` / `SeatObservationService`。"""

from ushareiplay.adapters.inbound.chat.base_command import BaseCommand


class SeatCommand(BaseCommand):
    handler_attr = "soul_handler"
    error_message = "Failed to process seat command: {error}"

    async def process(self, message_info, parameters):
        try:
            return await super().process(message_info, parameters)
        finally:
            self._log_seating_layout()

    def _log_seating_layout(self):
        try:
            obs = getattr(self.controller, "seat_observation", None)
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
                self.soul_handler.log_error(
                    f"Error logging seat layout after seat command: {e}"
                )

    async def _resolve_visible_username(self, nickname: str) -> str:
        """把昵称解析成 Soul UI 房间里可见的名字（分身名），解析不了则原样返回。"""
        if not nickname:
            return nickname
        try:
            return await self.info_manager.resolve_visible_username(nickname)
        except Exception:
            return nickname

    async def do_process(self, message_info, parameters):
        """Process seat command."""
        room_state = self.controller.room_state
        if room_state is not None and room_state.is_guest_room:
            return {"error": "他人房间不支持座位功能"}

        seat_service = self.controller.seat_service

        if not parameters:
            return await seat_service.find_owner_seat(force_relocate=True)

        command = parameters[0]

        if command == "0":
            return await seat_service.remove_user_reservation(message_info.nickname)
        elif command == "1" and len(parameters) == 2:
            seat_number, err = self.coerce_int(
                parameters[1], 1, 12, "Invalid seat number. Must be between 1 and 12"
            )
            if err:
                return {"error": err}
            return await seat_service.reserve_seat(message_info.nickname, seat_number)
        elif command == "2" and len(parameters) == 2:
            seat_number, err = self.coerce_int(
                parameters[1], 1, 12, "Invalid seat number. Must be between 1 and 12"
            )
            if err:
                return {"error": err}
            return await seat_service.take_seat(seat_number)
        elif command == "3":
            target_username = (
                parameters[1].strip() if len(parameters) > 1 else message_info.nickname
            ) or ""
            target_username = await self._resolve_visible_username(target_username)
            return await seat_service.accompany_user(
                target_username, sender_username=message_info.nickname
            )
        elif command == "4":
            if len(parameters) == 1:
                return await seat_service.remove_seat_occupant(None)
            if len(parameters) == 2:
                seat_number, err = self.coerce_int(
                    parameters[1], 1, 12, "Invalid seat number. Must be between 1 and 12"
                )
                if err:
                    return {"error": err}
                return await seat_service.remove_seat_occupant(seat_number)
            return {"error": "Invalid command. Use: :seat 4 [seat_number]"}
        elif command == "5":
            if len(parameters) < 2:
                return {
                    "error": "Invalid command. Use: :seat 5 <seat_number> [username]"
                }
            seat_number, err = self.coerce_int(
                parameters[1], 1, 12, "Invalid seat number. Must be between 1 and 12"
            )
            if err:
                return {"error": err}
            target_username = (
                parameters[2].strip() if len(parameters) > 2 else message_info.nickname
            ) or ""
            target_username = await self._resolve_visible_username(target_username)
            return await seat_service.invite_user_to_seat(seat_number, target_username)
        else:
            return {
                "error": "Invalid command. Use: :seat [0|1 <seat_number>|2 <seat_number>|3 [username]|4 [seat_number]|5 <seat_number> [username]]"
            }
