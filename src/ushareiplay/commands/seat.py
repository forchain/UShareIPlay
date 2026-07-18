import traceback
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.seat_manager import SeatManager


class SeatCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = 'Failed to process seat command: {error}'

    async def do_process(self, message_info, parameters):
        """Process seat command"""
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
            target_username = parameters[1] if len(parameters) > 1 else message_info.nickname
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
            # Check seats when user enters, passing the username
            await SeatManager.get_instance().check_seats_on_entry(username)
        except Exception as e:
            self.handler.log_error(f"Error checking seats on user enter: {traceback.format_exc()}")

    async def user_return(self, username: str):
        """Called when a user returns to the party"""
        try:
            # Check seats when user returns, passing the username
            await SeatManager.get_instance().check_seats_on_entry(username)
        except Exception as e:
            self.handler.log_error(f"Error checking seats on user return: {traceback.format_exc()}")

    def update(self):
        """Update method - focus count monitoring has been migrated to event system"""
        # 专注数监控已迁移到事件系统，不再需要手动调用
        pass
