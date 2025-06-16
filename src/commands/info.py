import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time


def create_command(controller):
    info_command = InfoCommand(controller)
    controller.info_command = info_command
    return info_command


command = None


class InfoCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        self.last_user_count = None

    async def process(self, message_info, parameters):
        result = self.music_handler.get_playback_info()
        result['player'] = self.controller.player_name
        return result

    def update(self):
        """Check and log user count changes"""
        try:
            user_count_elem = self.handler.try_find_element_plus('user_count', log=False)
            if not user_count_elem:
                return

            current_count = user_count_elem.text
            if current_count == self.last_user_count:
                return

            self.handler.logger.info(f"User count changed: {self.last_user_count} -> {current_count}")
            self.last_user_count = current_count

            user_count_elem.click()
            self.handler.logger.info("Clicked user count element")

            online_user = self.handler.wait_for_element_plus('online_user')
            if online_user:
                online_users = self.handler.find_elements_plus('online_user')
                for user in online_users:
                    user_text = user.text
                    self.handler.logger.info(f"Online user: {user_text}")
            else:
                self.handler.logger.error("No online user found")

            bottom_drawer = self.handler.wait_for_element_plus('bottom_drawer')
            if bottom_drawer:
                self.handler.logger.info(f'Hide online users dialog')
                self.handler.click_element_at(bottom_drawer, 0.5, -0.1)

        except Exception as e:
            self.handler.log_error(f"Error checking user count: {traceback.format_exc()}")
