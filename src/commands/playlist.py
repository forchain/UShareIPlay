import traceback

from appium.webdriver.common.appiumby import AppiumBy

from ..core.base_command import BaseCommand
from ..helpers.playlist_parser import PlaylistParser


def create_command(controller):
    playlist_command = PlaylistCommand(controller)
    controller.playlist_command = playlist_command
    return playlist_command


command = None


class PlaylistCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    async def process(self, message_info, parameters):
        query = ' '.join(parameters)

        if len(parameters) == 0:
            playing_info = self.handler.get_playlist_info()
        else:
            self.controller.player_name = message_info.nickname
            self.soul_handler.ensure_mic_active()
            playing_info = self.play_playlist(query)

        return playing_info

    def select_playlist_tab(self):
        """Select the 'Playlist' tab in search results by scrolling to the leftmost position"""
        try:
            # Try to find playlist tab first
            playlist_tab = self.handler.try_find_element_plus('playlist_tab')
            if not playlist_tab:
                # If not found, scroll music_tabs to find it
                music_tabs = self.handler.try_find_element_plus('music_tabs')
                if not music_tabs:
                    self.handler.logger.error("Failed to find music tabs")
                    return False

                # Get size and location for scrolling
                size = music_tabs.size
                location = music_tabs.location

                # Scroll to left (opposite direction of singer tab)
                self.handler.driver.swipe(
                    location['x'] + 200,  # Start from left
                    location['y'] + size['height'] // 2,
                    location['x'] + size['width'] - 10,  # End at right
                    location['y'] + size['height'] // 2,
                    1000
                )

                # Try to find playlist tab again
                playlist_tab = self.handler.try_find_element_plus('playlist_tab')
                if not playlist_tab:
                    self.handler.logger.error("Failed to find playlist tab after scrolling")
                    return False

            playlist_tab.click()
            self.handler.logger.info("Selected playlist tab")
            return True

        except Exception as e:
            self.handler.logger.error(f"Error selecting playlist tab: {traceback.format_exc()}")
            return False

    def play_playlist(self, query: str):
        if not self.handler.query_music(query):
            self.handler.logger.error('Failed to query music in playlist')
            return {
                'error': 'Failed to query music playlist',
            }

        if not self.select_playlist_tab():
            self.handler.logger.error('Failed to find playlist tab')
            return {
                'error': 'Failed to find playlist tab',
            }
        self.handler.logger.info("Selected playlist tab")

        result = self.handler.wait_for_element_clickable_plus('playlist_result')
        result.click()
        self.handler.logger.info("Selected playlist result")

        playlist = result.text
        parser = PlaylistParser()

        subject, topic = parser.parse_playlist_name(playlist)

        result_item = self.handler.try_find_element_plus('result_item')
        song_name = None
        singer_name = None
        if result_item:
            elements = self.handler.find_child_elements(result_item, AppiumBy.CLASS_NAME, 'android.widget.LinearLayout')
            if elements:
                song_name = self.handler.find_child_element(elements[0], AppiumBy.CLASS_NAME, 'android.widget.TextView')
                if len(elements) > 1:
                    singer_name = self.handler.find_child_element(elements[1], AppiumBy.CLASS_NAME, 'android.widget.TextView')

        if not subject:
            self.handler.logger.warning('Failed to parse playlist name')
            if singer_name:
                subject = singer_name.text

        if not topic:
            self.handler.logger.warning('Failed to parse playlist topic')
            if song_name:
                topic = song_name.text

        key, play_button = self.handler.wait_for_any_element_plus(['play_all', 'play_all_playlist'])
        if not play_button:
            self.handler.logger.error("Failed to find play all button (album or playlist)")
            return {
                'error': 'Failed to find play all button',
            }

        play_button.click()
        self.handler.logger.info("Selected play all button")

        playing_info = self.handler.get_playlist_info()
        if not 'error' in playing_info:
            playlist = f'Playing {playlist}\n\n{playing_info["playlist"]}'

        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title_manager.set_next_title(subject)
        topic_manager.change_topic(topic)
        self.handler.list_mode = 'playlist'
        return {
            'playlist': playlist,
        }
