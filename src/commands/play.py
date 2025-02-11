import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    play_command = PlayCommand(controller)
    controller.play_command = play_command
    return play_command

command = None

class PlayCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

        self.handler = controller.music_handler

    def process(self, message_info, parameters):
        query = ' '.join(parameters)
        self.soul_handler.ensure_mic_active()

        if query == '?':
            playing_info = self.play_favorites()
            self.controller.player_name = message_info.nickname
            return playing_info
        elif query == '':
            playing_info = self.play_radar()
            self.controller.player_name = message_info.nickname
            return playing_info
        else:
            playing_info = self.play_song(query)
            return playing_info

    def play_song(self, music_query):
        """Search and play music"""
        if music_query == '?':
            playing_info = self.play_favorites()
            return playing_info
        elif music_query == '':
            playing_info = self.play_radar()
            return playing_info

        playing_info = self.handler._prepare_music_playback(music_query)
        if 'error' in playing_info:
            self.handler.logger.error(f'Failed to play music {music_query}')
            return playing_info

        song_element = self.handler.wait_for_element_clickable_plus('song_name')
        song_element.click()
        self.handler.logger.info(f"Select first song")

        return playing_info

    def play_favorites(self):
        """Navigate to favorites and play all"""
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.press_back()
        my_nav = self.handler.try_find_element_plus('my_nav', log=False)
        if not my_nav:
            self.handler.press_back()
            my_nav = self.handler.try_find_element_plus('my_nav')
            if not my_nav:
                return {'error': 'Cannot find my_nav'}

        self.handler.logger.info("Navigated to home page")

        my_nav.click()
        self.handler.logger.info("Clicked personal info navigation button")

        # Click on favorites button
        fav_entry = self.handler.wait_for_element_clickable_plus('fav_entry')
        fav_entry.click()
        self.handler.logger.info("Clicked favorites button")

        # Click on play all button
        play_fav = self.handler.wait_for_element_clickable_plus('play_fav')
        song = self.handler.wait_for_element_clickable_plus('fav_song')
        singer = self.handler.wait_for_element_clickable_plus('fav_singer')

        play_fav.click()
        self.handler.logger.info("Clicked play all button")

        self.controller.topic_command.change_topic("Joyer Radio")
        self.controller.title_command.change_title("Joyer Radio")

        return {'song': song.text, 'singer': singer.text}

    def play_radar(self):
        """Navigate to favorites and play all"""
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.press_back()
        radar_nav = self.handler.try_find_element_plus('radar_nav', log=False)
        if not radar_nav:
            self.handler.press_back()
            radar_nav = self.handler.try_find_element_plus('radar_nav')
            if not radar_nav:
                return {'error': 'Cannot find radar_nav'}

        self.handler.logger.info("Navigated to home page")

        radar_nav.click()
        self.handler.logger.info("Clicked radar navigation button")

        self.controller.topic_command.change_topic("Outlier Station")
        self.controller.title_command.change_title("Outlier电台")

        # Click on play all button
        song = self.handler.wait_for_element_clickable_plus('radar_song')
        singer = self.handler.wait_for_element_clickable_plus('radar_singer')

        return {'song': song.text, 'singer': singer.text}
