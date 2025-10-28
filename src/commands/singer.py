import traceback

from ..core.base_command import BaseCommand


def create_command(controller):
    singer_command = SingerCommand(controller)
    controller.singer_command = singer_command
    return singer_command


command = None


class SingerCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    async def process(self, message_info, parameters):
        query = ' '.join(parameters)
        
        # 检查是否有其他用户正在播放列表
        from ..managers.info_manager import InfoManager
        info_manager = InfoManager.instance()
        player_name = info_manager.player_name
        # 排除系统用户 Joyer 和 Timer
        if player_name and player_name != message_info.nickname and player_name not in ["Joyer", "Timer", "Outlier"]:
            # 检查之前的播放者是否还在线
            if info_manager.is_user_online(player_name):
                self.handler.logger.info(f"{message_info.nickname} 尝试播放歌手歌单，但 {player_name} 正在播放")
                return {'error': f'{player_name} 正在播放歌单，请等待'}
        
        self.soul_handler.ensure_mic_active()
        info_manager.player_name = message_info.nickname
        info = self.play_singer(query)
        return info

    def select_singer_tab(self):
        """Select the 'Singer' tab in search results"""
        try:
            # Try to find singer tab first
            singer_tab = self.handler.try_find_element_plus('singer_tab')
            if not singer_tab:
                # If not found, scroll music_tabs to find it
                music_tabs = self.handler.wait_for_element_clickable_plus('music_tabs')
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

        singer_text = self.handler.wait_for_element_clickable_plus('singer_text')
        if not singer_text:
            return {
                'error': 'Failed to find singer result',
            }

        singer_text.click()
        self.handler.logger.info("Selected singer result")

        singer_name = singer_text.text

        play_button = self.handler.wait_for_element_clickable_plus('play_all_singer')
        if not play_button:
            self.handler.logger.error("Cannot find play singer button")
            return {'error': 'Failed to find play button'}
        play_button.click()

        self.handler.logger.info("Clicked play singer result")

        # Get playlist info from UI instead of ADB
        playing_info = self.handler.get_playlist_info()
        if 'error' in playing_info:
            self.handler.logger.error(f"Failed to get playlist info: {playing_info['error']}")
            return playing_info
        
        # Extract first song from playlist as topic
        playlist_text = playing_info.get('playlist', '')
        if playlist_text:
            first_song = playlist_text.split('-')[0].strip()
            topic = first_song if first_song else singer_name
        else:
            topic = singer_name
        
        # Format playlist with singer name
        formatted_playlist = f'Playing {singer_name}\n\n{playlist_text}'

        self.handler.list_mode = 'singer'

        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        from ..managers.info_manager import InfoManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title_manager.set_next_title(singer_name)
        topic_manager.change_topic(topic)
        
        # 存储完整的歌单名称到 InfoManager
        info_manager = InfoManager.instance()
        info_manager.current_playlist_name = singer_name

        return {
            'singer': formatted_playlist,
        }
