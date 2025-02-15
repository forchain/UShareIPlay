import traceback
from ..core.base_command import BaseCommand

def create_command(controller):
    seat_command = SeatCommand(controller)
    controller.seat_command = seat_command
    return seat_command

command = None

class SeatCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    def be_seated(self):
        try:
            # Find all seat containers
            seat_containers = self.handler.find_elements_plus('seat_container')
            if not seat_containers:
                self.handler.logger.error("Failed to find seat containers")
                return {'error': 'Failed to find seat containers'}

            # Try to find a seat next to someone
            for container in seat_containers:
                # Check both seats in this container
                left_state = self.handler.find_child_element_plus(container, 'left_state')
                right_state = self.handler.find_child_element_plus(container, 'right_state')

                # If left seat is empty and right seat has someone
                if not left_state and right_state:
                    left_seat = self.handler.find_child_element_plus(container, 'left_seat')
                    if left_seat:
                        left_seat.click()
                        self.handler.logger.info("Clicked left seat next to occupied right seat")
                        return self._confirm_seat()

                # If right seat is empty and left seat has someone
                if not right_state and left_state:
                    right_seat = self.handler.find_child_element_plus(container, 'right_seat')
                    if right_seat:
                        right_seat.click()
                        self.handler.logger.info("Clicked right seat next to occupied left seat")
                        return self._confirm_seat()

            # If no seats next to someone found, try any available seat
            apply_seat = self.handler.wait_for_element_clickable_plus('apply_seat')
            if not apply_seat:
                self.handler.logger.error("Failed to find any available seat")
                return {'error': 'Failed to find any available seat'}
            
            apply_seat.click()
            self.handler.logger.info("Clicked available seat")
            return self._confirm_seat()

        except Exception as e:
            self.handler.log_error(f"Error applying for seat: {traceback.format_exc()}")
            return {'error': 'Failed to apply for seat'}

    def _confirm_seat(self):
        """Helper method to confirm seat selection"""
        confirm_seat = self.handler.wait_for_element_clickable_plus('confirm_seat')
        if not confirm_seat:
            self.handler.logger.error("Failed to find confirm seat button")
            return {'error': 'Failed to find confirm seat button'}
            
        confirm_seat.click()
        self.handler.logger.info("Clicked confirm seat button")
        return {'success': 'Successfully applied for seat'}

    def process(self, message_info, parameters):
        return self.be_seated() 