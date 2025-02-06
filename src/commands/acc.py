import traceback
from ..core.base_command import BaseCommand
from appium.webdriver.common.appiumby import AppiumBy
from datetime import datetime, timedelta
import time

def create_command(controller):
    accompaniment_command = AccompanimentCommand(controller)
    controller.accompaniment_command = accompaniment_command
    return accompaniment_command

command = None

class AccompanimentCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    def process(self, message_info, parameters):
        # Get parameter
        if len(parameters) == 0:
            return {
                'error': 'Missing parameter (on:1, off:0) for accompaniment command'
            }

        enable = parameters[0] == '1'
        # Toggle accompaniment mode
        return self.toggle_accompaniment(enable)

    def toggle_accompaniment(self, enable):
        """Toggle accompaniment mode
        Args:
            enable: bool, True to enable, False to disable
        Returns:
            dict: {'enabled': 'on'/'off'}
        """
        if not self.handler.switch_to_app():
            return {'error': 'Failed to switch to QQ Music app'}
        self.handler.logger.info("Switched to QQ Music app")

        error = self.handler.switch_to_playing_page()
        if error:
            return error

        tag = self.handler.try_find_element_plus('accompaniment_tag')

        if tag:
            self.handler.logger.info(f"Found accompaniment tag")
            is_on = True
        else:
            is_on = False

        # Toggle if needed
        if (enable and not is_on) or (not enable and is_on):
            if is_on:
                tag.click()
                switch = self.handler.wait_for_element_clickable_plus('accompaniment_switch')
                switch.click()
            else:
                more_menu = self.handler.wait_for_element_clickable_plus('more_in_play_panel')
                more_menu.click()
                self.handler.logger.info(f"Selected more menu")
                
                found = False
                for _ in range(9):
                    self.handler.press_dpad_down()
                    acc_menu = self.handler.try_find_element_plus('accompaniment_menu')
                    if acc_menu:
                        found = True
                        acc_menu.click()
                        self.handler.logger.info(f"Selected accompaniment menu")
                        
                        acc_label = self.handler.wait_for_element_clickable_plus(
                            'accompaniment_label',
                            timeout=2
                        )
                        if acc_label:
                            # Use new click_element_at method to click at 3/4 width
                            if not self.handler.click_element_at(acc_label, x_ratio=0.75):
                                self.handler.logger.error("Failed to click accompaniment label")
                                return {'error': 'Failed to click accompaniment label'}
                            break
                
                if not found:
                    return {'error': 'Failed to find accompaniment menu'}

        return {'enabled': 'on' if enable else 'off'}
