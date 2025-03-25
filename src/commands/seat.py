import traceback
from ..core.base_command import BaseCommand
from ..managers.seat_manager import SeatManager

def create_command(controller):
    seat_command = SeatCommand(controller)
    controller.seat_command = seat_command
    return seat_command

command = None

class SeatCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        # Initialize the singleton SeatManager
        self.seat_manager = SeatManager(self.handler)

    async def process(self, message_info, parameters):
        """Process seat command"""
        try:
            if not parameters:
                # No parameters - find and take an available seat
                return await self.seat_manager.be_seated()

            # Parse parameters
            parts = parameters.split()
            if len(parts) == 0:
                return {'error': 'Invalid parameters'}

            command = parts[0]
            
            if command == '0':
                # Remove user's reservations
                return await self.seat_manager.remove_user_reservation(message_info.nickname)
            elif command == '1' and len(parts) == 2:
                # Reserve specific seat
                try:
                    seat_number = int(parts[1])
                    if seat_number < 1 or seat_number > 12:
                        return {'error': 'Invalid seat number. Must be between 1 and 12'}
                    return await self.seat_manager.reserve_seat(message_info.nickname, seat_number)
                except ValueError:
                    return {'error': 'Invalid seat number. Must be a number between 1 and 12'}
            else:
                return {'error': 'Invalid command. Use: :seat [0|1 <seat_number>]'}

        except Exception as e:
            self.handler.log_error(f"Error processing seat command: {traceback.format_exc()}")
            return {'error': f'Failed to process seat command: {str(e)}'}

    async def check_and_remove_users(self):
        """Check and remove users from reserved seats"""
        seat_manager = SeatManager.get_instance()
        await seat_manager.check_and_remove_users()

    def user_enter(self, username: str):
        """Called when a user enters the party"""
        try:
            # Check seats when user enters, passing the username
            self.seat_manager.check_seats_on_entry(username)
        except Exception as e:
            self.handler.log_error(f"Error checking seats on user enter: {traceback.format_exc()}")

    def update(self):
        """Update focus count"""
        try:
            self.seat_manager.update()
        except Exception as e:
            self.handler.log_error(f"Error updating focus count: {traceback.format_exc()}")