import traceback
from ..core.base_command import BaseCommand
from ..managers.seat_manager import seat_manager


def create_command(controller):
    seat_command = SeatCommand(controller)
    return seat_command


command = None


class SeatCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = controller.soul_handler  # Add handler reference

    async def process(self, message_info, parameters):
        """Process seat command"""
        try:
            if not parameters:
                # No parameters - find and take an available seat for owner
                return seat_manager.seating.find_owner_seat(force_relocate=True)

            # Parse parameters
            if len(parameters) == 0:
                return {'error': 'Invalid parameters'}

            command = parameters[0]

            if command == '0':
                # Remove user's reservations
                return await seat_manager.reservation.remove_user_reservation(message_info.nickname)
            elif command == '1' and len(parameters) == 2:
                # Reserve specific seat
                try:
                    seat_number = int(parameters[1])
                    if seat_number < 1 or seat_number > 12:
                        return {'error': 'Invalid seat number. Must be between 1 and 12'}
                    return await seat_manager.reservation.reserve_seat(message_info.nickname, seat_number)
                except ValueError:
                    return {'error': 'Invalid seat number. Must be a number between 1 and 12'}
            elif command == '2' and len(parameters) == 2:
                # Sit at specific seat position
                try:
                    seat_number = int(parameters[1])
                    if seat_number < 1 or seat_number > 12:
                        return {'error': 'Invalid seat number. Must be between 1 and 12'}
                    return seat_manager.seating.sit_at_specific_seat(seat_number)
                except ValueError:
                    return {'error': 'Invalid seat number. Must be a number between 1 and 12'}
            else:
                return {'error': 'Invalid command. Use: :seat [0|1 <seat_number>|2 <seat_number>]'}

        except Exception as e:
            self.handler.log_error(f"Error processing seat command: {traceback.format_exc()}")
            return {'error': f'Failed to process seat command: {str(e)}'}

    async def user_enter(self, username: str):
        """Called when a user enters the party"""
        try:
            # Check seats when user enters, passing the username
            await seat_manager.check.check_seats_on_entry(username)
        except Exception as e:
            self.handler.log_error(f"Error checking seats on user enter: {traceback.format_exc()}")

    def update(self):
        """Update focus count"""
        try:
            seat_manager.focus.update()
        except Exception as e:
            self.handler.log_error(f"Error updating focus count: {traceback.format_exc()}")
