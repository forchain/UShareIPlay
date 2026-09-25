from ushareiplay.core.base_command import BaseCommand
from ushareiplay.helpers.playlist_info import get_playlist_text_and_first_song
from ushareiplay.managers.music_manager import MusicManager


class AlbumCommand(BaseCommand):
    playback_muting = True
    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        query = ' '.join(parameters)

        # 歌单守护检查：若当前播放者不是管理员且仍在房间（含分身），阻断切歌
        config = getattr(self.controller, "config", None)
        protection_error = await self.info_manager.check_playlist_protection(
            message_info.nickname, config=config
        )
        if protection_error:
            self.handler.logger.info(
                f"{message_info.nickname} 尝试播放专辑，但 {self.info_manager.player_name} 正在播放"
            )
            return protection_error

        self.info_manager.player_name = message_info.nickname
        info = self.play_album(query)
        return info

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
        if not self.music_manager.select_tab('album'):
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

        # 使用 room_name_manager 和 topic_manager 管理标题和话题
        self.topic_manager.change_topic(topic)
        self.handler.logger.info(f"changing album topic to {topic}")
        self.room_name_manager.set_next_title(title)
        self.handler.logger.info(f"changing album title  to {title}")

        # 存储完整的歌单名称到 InfoManager
        self.info_manager.current_playlist_name = f"{title} - {topic}"

        return {
            'playlist': playlist_text
        }
