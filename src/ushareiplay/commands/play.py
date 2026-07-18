from appium.webdriver.common.appiumby import AppiumBy

from ushareiplay.core.base_command import BaseCommand


class PlayCommand(BaseCommand):
    requires_mic = True
    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        query = ' '.join(parameters)

        if query == '':
            playing_info = self.play_favorites()
            self.info_manager.player_name = message_info.nickname
            return playing_info
        elif query == '?':
            playing_info = self.play_radar()
            self.info_manager.player_name = message_info.nickname
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

        song_element = self.handler.element_finder.wait_for_element_clickable('result_item')
        song_element.click()
        self.handler.logger.info("Select first song")

        # 播放页会自动弹出：未收藏则自动收藏
        self.handler.ensure_favorited_in_playing_page(timeout=10)
        self.handler.handle_song_quality_check(playing_info)

        return playing_info

    def play_favorites(self):
        """Navigate to favorites and play all"""
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        err = self.handler.open_favorites_entry()
        if err:
            return err

        result_item = self.handler.element_finder.try_find_element('result_item')
        song_text = None
        singer_text = None
        if result_item:
            elements = result_item.find_elements(AppiumBy.CLASS_NAME, 'android.widget.TextView')
            if len(elements) >= 3:
                song_text = elements[1].text
                singer_text = elements[2].text

        play_fav = self.handler.element_finder.wait_for_element_clickable('play_all')
        if not play_fav:
            return {'error': 'Cannot find play all button'}
        play_fav.click()
        self.handler.logger.info("Clicked play all button")

        self.handler.list_mode = 'favorites'
        # 使用 title_manager 和 topic_manager 管理标题和话题
        self.title_manager.set_next_title("O Station")
        self.topic_manager.change_topic(song_text)

        return {'song': song_text, 'singer': singer_text, 'album': ''}

    def play_radar(self):
        """Navigate to favorites and play all"""
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.navigate_to_home()
        self.handler.logger.info("Navigated to home page")
        radar_nav = self.handler.element_finder.try_find_element('radar_nav', log=False)
        if not radar_nav:
            return {'error': 'Cannot find radar_nav'}

        radar_nav.click()
        self.handler.logger.info("Clicked radar navigation button")

        self.handler.list_mode = 'radar'

        # Click on play all button
        song = self.handler.element_finder.wait_for_element_clickable('radar_song')
        song_text = song.text if song else "Unknown"
        singer = self.handler.element_finder.wait_for_element_clickable('radar_singer')
        singer_text = singer.text if singer else "Unknown"

        # 使用 title_manager 和 topic_manager 管理标题和话题
        self.title_manager.set_next_title("O Radio")
        self.topic_manager.change_topic(song_text)

        return {'song': song_text, 'singer': singer_text, 'album': ''}
