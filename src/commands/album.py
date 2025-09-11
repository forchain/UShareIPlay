import traceback

from ..core.base_command import BaseCommand


def create_command(controller):
    album_command = AlbumCommand(controller)
    controller.album_command = album_command
    return album_command


command = None


class AlbumCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    async def process(self, message_info, parameters):
        query = ' '.join(parameters)
        self.soul_handler.ensure_mic_active()
        self.controller.player_name = message_info.nickname
        info = self.play_album(query)
        return info

    def select_album_tab(self):
        """Select the 'Album' tab in search results"""
        try:
            # Try to find album tab first
            album_tab = self.handler.try_find_element_plus('album_tab')
            if not album_tab:
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

                # Try to find album tab again
                album_tab = self.handler.try_find_element_plus('album_tab')
                if not album_tab:
                    self.handler.logger.error("Failed to find album tab after scrolling")
                    return False

            album_tab.click()
            self.handler.logger.info("Selected album tab")
            return True

        except Exception as e:
            self.handler.logger.error(f"Error selecting album tab: {traceback.format_exc()}")
            return False

    def play_album(self, query):
        if query == "":
            info = self.handler.get_playback_info()
            if not info:
                self.handler.logger.error(f"Failed to get playback info with query {query}")
                return {'error': f'Failed to get playback info'}
            query = f'{info["song"]} {info["singer"]} {info["album"]}'
        if not self.handler.query_music(query):
            self.handler.logger.error(f"Failed to query music with query {query}")
            return {
                'error': 'Failed to query album',
            }
        if not self.select_album_tab():
            self.handler.logger.error(f"Failed to select lyrics tab with query {query}")
            return {
                'error': 'Failed to select lyrics tab',
            }

        album_text = self.handler.wait_for_element_clickable_plus('album_text')
        if not album_text:
            self.handler.logger.error(f"Failed to find album text with query {query}")
            return {'error': 'Failed to find album text'}
        topic = album_text.text
        album_singer = self.handler.try_find_element_plus('album_singer')
        if not album_singer:
            self.handler.logger.error(f"Failed to find album singer with query {query}")
            return {'error': f'Failed to find album singer with query {query}'}
        title = album_singer.text

        album_text.click()
        self.handler.logger.info("album text clicked")

        key, play_button = self.handler.wait_for_any_element_plus(['play_all', 'play_all_mini'])
        if not play_button:
            self.handler.logger.error(f"Failed to find play button for query {query}")
            return {'error': 'Failed to find play button'}

        play_button.click()
        self.handler.logger.info("play button clicked")
        self.handler.press_back()

        self.handler.list_mode = 'album'

        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        topic_manager.change_topic(topic)
        self.handler.logger.info(f"changing album topic to {topic}")
        title_manager.set_next_title(title)
        self.handler.logger.info(f"changing album title  to {title}")

        return {
            'album': topic
        }
