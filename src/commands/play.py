from appium.webdriver.common.appiumby import AppiumBy

from ..core.base_command import BaseCommand


def create_command(controller):
    play_command = PlayCommand(controller)
    controller.play_command = play_command
    return play_command


command = None


class PlayCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

        self.handler = controller.music_handler

    async def process(self, message_info, parameters):
        query = ' '.join(parameters)
        self.soul_handler.ensure_mic_active()

        from ..managers.info_manager import InfoManager
        info_manager = InfoManager.instance()

        if query == '?':
            playing_info = self.play_favorites()
            info_manager.player_name = message_info.nickname
            return playing_info
        elif query == '':
            playing_info = self.play_radar()
            info_manager.player_name = message_info.nickname
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

        song_element = self.handler.wait_for_element_clickable_plus('result_item')
        song_element.click()
        self.handler.logger.info("Select first song")

        return playing_info

    def play_favorites(self):
        """Navigate to favorites and play all"""
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.navigate_to_home()
        self.handler.logger.info("Navigated to home page")

        my_nav = self.handler.wait_for_element_clickable_plus('my_nav')
        my_nav.click()
        self.handler.logger.info("Clicked personal info navigation button")

        # Click on favorites button
        fav_entry = self.handler.wait_for_element_clickable_plus('fav_entry')
        fav_entry.click()
        self.handler.logger.info("Clicked favorites button")

        result_item = self.handler.try_find_element_plus('result_item')
        song_text = None
        singer_text = None
        if result_item:
            elements = self.handler.find_child_elements(result_item, AppiumBy.CLASS_NAME, 'android.widget.TextView')
            if len(elements) >= 3:
                song_text = elements[1].text
                singer_text = elements[2].text

        play_fav = self.handler.wait_for_element_clickable_plus('play_all')
        play_fav.click()
        self.handler.logger.info("Clicked play all button")

        self.handler.list_mode = 'favorites'
        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title_manager.set_next_title("O Station")
        topic_manager.change_topic(song_text)

        return {'song': song_text, 'singer': singer_text, 'album': ''}

    def play_radar(self):
        """Navigate to favorites and play all"""
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.navigate_to_home()
        self.handler.logger.info("Navigated to home page")
        radar_nav = self.handler.try_find_element_plus('radar_nav', log=False)
        if not radar_nav:
            return {'error': 'Cannot find radar_nav'}

        radar_nav.click()
        self.handler.logger.info("Clicked radar navigation button")

        self.handler.list_mode = 'radar'

        # Click on play all button
        song = self.handler.wait_for_element_clickable_plus('radar_song')
        song_text = song.text if song else "Unknown"
        singer = self.handler.wait_for_element_clickable_plus('radar_singer')
        singer_text = singer.text if singer else "Unknown"

        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title_manager.set_next_title("O Radio")
        topic_manager.change_topic(song_text)

        return {'song': song_text, 'singer': singer_text, 'album': ''}
