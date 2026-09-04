import traceback

from appium.webdriver.common.appiumby import AppiumBy

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.helpers.playlist_info import get_playlist_text_and_first_song
from ushareiplay.helpers.playlist_parser import PlaylistParser

class PlaylistCommand(BaseCommand):
    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        query = ' '.join(parameters)

        if len(parameters) == 0:
            playing_info = self.handler.get_playlist_info()
        else:
            # 歌单守护检查：若当前播放者不是管理员且仍在房间（含分身），阻断切歌
            config = getattr(self.controller, "config", None)
            protection_error = await self.info_manager.check_playlist_protection(
                message_info.nickname, config=config
            )
            if protection_error:
                self.handler.logger.info(
                    f"{message_info.nickname} 尝试播放歌单，但 {self.info_manager.player_name} 正在播放"
                )
                return protection_error

            info_manager.player_name = message_info.nickname
            self.soul_handler.ensure_mic_active()
            playing_info = self.play_playlist(query)

        return playing_info

    def select_playlist_tab(self):
        """Select the 'Playlist' tab in search results"""
        try:
            # Try to find playlist tab first or music tabs container
            key, element = self.handler.element_finder.wait_for_any_element(['playlist_tab', 'music_tabs'])

            if key == 'playlist_tab':
                playlist_tab = element
            elif key == 'music_tabs':
                _, playlist_tab, _ = self.handler.gesture_handler.scroll_container_until_element(
                    'playlist_tab',
                    'music_tabs',
                    'left',
                    max_swipes=10,
                )
                if not playlist_tab:
                    playlist_tab = self.handler.element_finder.try_find_element('playlist_tab')
                    if not playlist_tab:
                        self.handler.logger.error("Failed to find playlist tab after scrolling")
                        return False
            else:
                self.handler.logger.error("Failed to find music tabs or playlist tab")
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

        key, element = self.handler.element_finder.wait_for_any_element(['playlist_result', 'not_found'])
        if not key or key == 'not_found':
            self.handler.logger.error(f"Failed to find playlist result with query {query}")
            return {
                'error': f'Failed to find playlist with query {query}',
            }

        result = element
        result.click()
        self.handler.logger.info("Selected playlist result")

        playlist = result.text
        original_playlist_name = playlist  # Store complete original name before parsing
        parser = PlaylistParser()

        subject, topic = parser.parse_playlist_name(playlist)

        result_item = self.handler.element_finder.try_find_element('result_item')
        song_name = None
        singer_name = None
        if result_item:
            elements = result_item.find_elements(AppiumBy.CLASS_NAME, 'android.widget.LinearLayout')
            if elements:
                song_name = elements[0].find_element(AppiumBy.CLASS_NAME, 'android.widget.TextView')
                if len(elements) > 1:
                    singer_name = elements[1].find_element(AppiumBy.CLASS_NAME, 'android.widget.TextView')

        if not subject:
            self.handler.logger.warning('Failed to parse playlist name')
            if singer_name:
                subject = singer_name.text

        if not topic:
            self.handler.logger.info('Failed to parse playlist topic')
            if song_name:
                topic = song_name.text

        key, play_button = self.handler.element_finder.wait_for_any_element(['play_all', 'play_all_playlist', 'play_all_compact'])
        if not play_button:
            self.handler.logger.error("Failed to find play all button (album or playlist)")
            return {
                'error': 'Failed to find play all button',
            }

        play_button.click()
        self.handler.logger.info("Selected play all button")

        playlist_info = self.handler.get_playlist_info()
        playlist_text, _, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            self.handler.logger.warning(f"Failed to read playlist after playback started: {error}")
            playlist_text = original_playlist_name

        # 使用 title_manager 和 topic_manager 管理标题和话题
        self.title_manager.set_next_title(subject)
        self.topic_manager.change_topic(topic)
        self.handler.list_mode = 'playlist'

        # 存储完整的歌单名称到 InfoManager
        self.info_manager.current_playlist_name = original_playlist_name

        return {
            'playlist': playlist_text,
        }
