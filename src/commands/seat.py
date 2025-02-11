import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    seat_command = SeatCommand(controller)
    controller.seat_command = seat_command
    return seat_command

command = None

class SeatCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        self.handler.seat_command = self

    def process(self, message_info, parameters):
        """Process seat command to apply for a seat
        Returns:
            dict: Result with success or error message
        """

        return  self.be_seated()
    
    def be_seated(self):
        try:
            # Find and click apply seat button
            apply_seat = self.handler.wait_for_element_clickable_plus('apply_seat')
            if not apply_seat:
                self.handler.logger.error("Failed to find apply seat button")
                return {'error': 'Failed to find apply seat button'}
            
            apply_seat.click()
            self.handler.logger.info("Clicked apply seat button")
            
            # Find and click confirm seat button
            confirm_seat = self.handler.wait_for_element_clickable_plus('confirm_seat')
            if not confirm_seat:
                self.handler.logger.error("Failed to find confirm seat button")
                return {'error': 'Failed to find confirm seat button'}
                
            confirm_seat.click()
            self.handler.logger.info("Clicked confirm seat button")
            
            return {'success': 'Successfully applied for seat'}
            
        except Exception as e:
            self.handler.log_error(f"Error applying for seat: {traceback.format_exc()}")
            return {'error': 'Failed to apply for seat'} 