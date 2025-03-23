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
                return {'error': 'Invalid parameters. Use: :seat 1 <seat_number> to reserve a seat'}

            # Parse parameters
            parts = parameters.split()
            if len(parts) != 2:
                return {'error': 'Invalid parameters. Use: :seat 1 <seat_number> to reserve a seat'}

            command, seat_number = parts[0], parts[1]
            if command != '1':
                return {'error': 'Invalid command. Use: :seat 1 <seat_number> to reserve a seat'}

            try:
                seat_number = int(seat_number)
                if seat_number < 1 or seat_number > 12:
                    return {'error': 'Invalid seat number. Must be between 1 and 12'}
            except ValueError:
                return {'error': 'Invalid seat number. Must be a number between 1 and 12'}

            # Get the singleton instance and delegate to seat manager for business logic
            seat_manager = SeatManager.get_instance()
            result = await seat_manager.reserve_seat(message_info.nickname, seat_number)
            return result

        except Exception as e:
            self.handler.log_error(f"Error processing seat command: {traceback.format_exc()}")
            return {'error': f'Failed to process seat command: {str(e)}'}

    async def check_and_remove_users(self):
        """Check and remove users from reserved seats"""
        seat_manager = SeatManager.get_instance()
        await seat_manager.check_and_remove_users()