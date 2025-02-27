import traceback
from ..core.base_command import BaseCommand
from appium.webdriver.common.appiumby import AppiumBy

def create_command(controller):
    singer_command = SingerCommand(controller)
    controller.singer_command = singer_command
    return singer_command


command = None


class SingerCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    def process(self, message_info, parameters):
        query = ' '.join(parameters)
        self.soul_handler.ensure_mic_active()
        self.controller.player_name = message_info.nickname
        info = self.play_singer(query)
        return info

    def select_singer_tab(self):
        """Select the 'Singer' tab in search results"""
        try:
            # Try to find singer tab first
            singer_tab = self.handler.try_find_element_plus('singer_tab')
            if not singer_tab:
                # If not found, scroll music_tabs to find it
                music_tabs = self.handler.try_find_element_plus('music_tabs')
                if not music_tabs:
                    self.handler.logger.error("Failed to find music tabs")
                    return False
                
                # Get size and location for scrolling
                size = music_tabs.size
                location = music_tabs.location
                
                # Scroll to right
                self.handler.driver.swipe(
                    location['x'] + 200,  # Start from left
                    location['y'] + size['height'] // 2,
                    location['x'] + size['width'] - 10,  # End at right
                    location['y'] + size['height'] // 2,
                    1000
                )
                
                # Try to find singer tab again
                singer_tab = self.handler.try_find_element_plus('singer_tab')
                if not singer_tab:
                    self.handler.logger.error("Failed to find singer tab after scrolling")
                    return False
            
            singer_tab.click()
            self.handler.logger.info("Selected singer tab")
            return True
            
        except Exception as e:
            self.handler.logger.error(f"Error selecting singer tab: {traceback.format_exc()}")
            return False

    def play_singer(self, query: str):

        if not self.handler.query_music(query):
            return {
                'error': 'Failed to query singer',
            }

        self.select_singer_tab()

        singer_result = self.handler.wait_for_element_clickable_plus('singer_result')
        if not singer_result:
            return {
                'error': 'Failed to find singer result',
            }

        singer_text = self.handler.find_child_element(singer_result, AppiumBy.ID, self.handler.config['elements']['singer_text'])
        singer_text.click()
        self.handler.logger.info("Selected singer result")

        singer_name = singer_text.text

        self.handler.wait_for_element_clickable_plus('singer_tabs')

        play_button = self.handler.try_find_element_plus('play_singer')
        if not play_button:
            song_tab = self.handler.try_find_element_plus('song_tab')
            if not song_tab:
                self.handler.logger.error("Cannot find singer song tab")
                return {
                    'error': 'Failed to find singer song tab',
                }
            song_tab.click()
            self.handler.logger.info("Selected singer tab")

            play_button = self.handler.wait_for_element_clickable_plus('play_singer')

        if not play_button:
            self.handler.logger.error(f"Cannot find play singer button")
            return {'error': 'Failed to find play button'}

        topic = singer_name
        song_name = self.handler.try_find_element_plus('song_name')
        if song_name:
            topic = song_name.text

        play_button.click()
        self.handler.logger.info("Clicked play singer result")

        singer_screen = self.handler.try_find_element_plus('singer_screen', log=False)
        if singer_screen:
            self.handler.logger.info(f"Found Singer screen")
            self.handler.press_back()

        self.handler.list_mode = 'singer'

        self.controller.title_command.change_title(singer_name)
        self.controller.topic_command.change_topic(topic)

        return {
            'singer': singer_name,
        }
