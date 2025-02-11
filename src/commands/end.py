import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    end_command = EndCommand(controller)
    controller.end_command = end_command
    return end_command

command = None

class EndCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        self.last_auto_end_date = None  # Track last auto end date
        self.auto_end_hour = 12  # Default auto end hour (12:00 PM)

    def process(self, message_info, parameters):
        """Process end command to close party"""
        try:
            # Check if user has relation tag (followed by host)
            if not message_info.relation_tag:
                self.handler.logger.warning(f"User {message_info.nickname} not followed by host, cannot end party")
                return {'error': '必须群主关注的人才能关闭房间'}
                
            return self.end_party()
        except Exception as e:
            self.handler.log_error(f"Error processing end command: {str(e)}")
            return {'error': 'Failed to end party'} 
    
    def end_party(self):
        """End party"""
        try:
            self.handler.send_message('Ending party')
            self.handler.end_party()
            return {'success': 'Party ended'}
        except Exception as e:
            self.handler.log_error(f"Error processing end command: {str(e)}")
            return {'error': 'Failed to end party'} 

    def update(self):
        """Check and auto end party if conditions are met"""
        try:
            current_time = datetime.now()
            current_date = current_time.date()

            # Check if we already auto-ended today
            if self.last_auto_end_date == current_date:
                return

            # Check if it's after auto end hour
            if current_time.hour < self.auto_end_hour:
                return

            # Get user count
            user_count_elem = self.handler.try_find_element_plus('user_count')
            if not user_count_elem:
                return

            user_count_text = user_count_elem.text
            if user_count_text == '1人':
                self.handler.logger.info("Only one user in party, auto ending...")
                result = self.end_party()
                if 'success' in result:
                    self.last_auto_end_date = current_date
                    self.handler.logger.info("Auto ended party successfully")

        except Exception as e:
            self.handler.log_error(f"Error in auto end update: {traceback.format_exc()}")
