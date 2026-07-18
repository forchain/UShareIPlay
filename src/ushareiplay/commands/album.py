import traceback

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.helpers.playlist_info import get_playlist_text_and_first_song
from ushareiplay.managers.music_manager import MusicManager


class AlbumCommand(BaseCommand):
    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        query = ' '.join(parameters)

        # 检查是否有其他用户正在播放列表
        info_manager = self.info_manager
        player_name = info_manager.player_name
        # 排除系统用户 Joyer 和 Timer
        if player_name and player_name != message_info.nickname and player_name not in ["Joyer", "Timer", "Outlier", "Chainer"]:
            # 检查之前的播放者是否还在线
            if info_manager.is_user_online(player_name):
                self.handler.logger.info(f"{message_info.nickname} 尝试播放专辑，但 {player_name} 正在播放")
                return {'error': f'{player_name} 正在播放歌单，请等待'}

        self.soul_handler.ensure_mic_active()
        info_manager.player_name = message_info.nickname
        info = self.play_album(query)
        return info

    def select_album_tab(self):
        """Select the 'Album' tab in search results"""
        try:
            # Try to find album tab first
            album_tab = self.handler.element_finder.try_find_element('album_tab')
            if not album_tab:
                # If not found, scroll music_tabs to find it
                music_tabs = self.handler.element_finder.try_find_element('music_tabs')
                if not music_tabs:
                    self.handler.logger.error("Failed to find music tabs")
                    return False

                # Get size and location for scrolling
                size = music_tabs.size
                location = music_tabs.location

                # Scroll to right
                self.handler.gesture_handler.swipe(
                    location['x'] + 200,  # Start from left
                    location['y'] + size['height'] // 2,
                    location['x'] + size['width'] - 10,  # End at right
                    location['y'] + size['height'] // 2,
                    1000
                )

                # Try to find album tab again
                album_tab = self.handler.element_finder.try_find_element('album_tab')
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
            info = MusicManager.instance().get_playback_info()
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
            self.handler.logger.error(f"Failed to select album tab with query {query}")
            return {
                'error': 'Failed to select album tab',
            }

        key, element = self.handler.element_finder.wait_for_any_element(['album_result', 'not_found'])
        if not key or key == 'not_found':
            self.handler.logger.error(f"Not found album result with query {query}")
            return {
                'error': f'Failed to find album result with query {query}',
            }
        album_result = self.handler.element_finder.find_elements('album_result')
        if len(album_result) < 2:
            self.handler.logger.error(f"Failed to find album result with query {query}")
            return {
                'error': 'Failed to find album result',
            }
        album_name =  album_result[0]
        album_singer = album_result[1]
        topic = album_name.text
        title = album_singer.text

        album_name.click()
        self.handler.logger.info("album name clicked")

        key, play_button = self.handler.element_finder.wait_for_any_element(['play_all'])
        if not play_button:
            self.handler.logger.error(f"Failed to find play button for query {query}")
            return {'error': 'Failed to find play button'}

        play_button.click()
        self.handler.logger.info("play button clicked")

        playlist_info = self.handler.get_playlist_info()
        playlist_text, _, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            self.handler.logger.warning(f"Failed to read album playlist after playback started: {error}")
            playlist_text = f"{title} - {topic}"

        self.handler.key_actions.press_back()

        self.handler.list_mode = 'album'

        # 使用 title_manager 和 topic_manager 管理标题和话题
        self.topic_manager.change_topic(topic)
        self.handler.logger.info(f"changing album topic to {topic}")
        self.title_manager.set_next_title(title)
        self.handler.logger.info(f"changing album title  to {title}")

        # 存储完整的歌单名称到 InfoManager
        self.info_manager.current_playlist_name = f"{title} - {topic}"

        return {
            'playlist': playlist_text
        }
