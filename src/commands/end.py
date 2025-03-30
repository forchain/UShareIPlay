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
        
        # Record initialization time
        self.init_time = datetime.now()
        self.handler.logger.info(f"EndCommand initialized at {self.init_time}")

    async def process(self, message_info, parameters):
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
            
            # Switch to Soul app first
            if not self.handler.switch_to_app():
                return {'error': 'Failed to switch to Soul app'}
            self.handler.logger.info("Switched to Soul app")

            # Click more menu
            more_menu = self.handler.wait_for_element_clickable_plus('more_menu')
            if not more_menu:
                return {'error': 'Failed to find more menu'}
            more_menu.click()
            self.handler.logger.info("Clicked more menu")

            # Click end party option
            end_party = self.handler.wait_for_element_clickable_plus('end_party')
            if not end_party:
                return {'error': 'Failed to find end party option'}
            end_party.click()
            self.handler.logger.info("Clicked end party option")

            # Click confirm end
            confirm_end = self.handler.wait_for_element_clickable_plus('confirm_end')
            if not confirm_end:
                return {'error': 'Failed to find confirm end button'}
            confirm_end.click()
            self.handler.logger.info("Clicked confirm end button")
            
            return {'success': 'Party ended'}
        except Exception as e:
            self.handler.log_error(f"Error processing end command: {traceback.format_exc()}")
            return {'error': 'Failed to end party'} 

    def update(self):
        """Check and auto end party if conditions are met"""
        try:
            current_time = datetime.now()
            current_date = current_time.date()
            current_hour = current_time.hour

            # Check if we already auto-ended today
            if self.last_auto_end_date == current_date:
                return

            # Only auto end if current hour is between 12 and 24 (noon to midnight)
            if current_hour < 12:
                return
                
            # Check if at least 12 hours have passed since initialization
            hours_since_init = (current_time - self.init_time).total_seconds() / 3600
            if hours_since_init < 12:
                return
                
            # Get user count
            user_count_elem = self.handler.try_find_element_plus('user_count', log=False)
            if not user_count_elem:
                return

            user_count_text = user_count_elem.text
            if user_count_text == '1人':
                self.handler.logger.info("Only one user in party, auto ending...")
                self.handler.logger.info(f"Hours since init: {hours_since_init:.2f}, current hour: {current_hour}")
                result = self.end_party()
                if 'success' in result:
                    self.last_auto_end_date = current_date
                    self.handler.logger.info("Auto ended party successfully")

        except Exception as e:
            self.handler.log_error(f"Error in auto end update: {traceback.format_exc()}")
