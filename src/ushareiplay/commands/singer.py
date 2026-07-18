import traceback

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.helpers.playlist_info import get_playlist_text_and_first_song


class SingerCommand(BaseCommand):
    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        query = " ".join(parameters)

        # 检查是否有其他用户正在播放列表
        info_manager = self.info_manager
        player_name = info_manager.player_name
        # 排除系统用户 Joyer 和 Timer
        if (
                player_name
                and player_name != message_info.nickname
                and player_name not in ["Joyer", "Timer", "Outlier", "Chainer"]
        ):
            # 检查之前的播放者是否还在线
            if info_manager.is_user_online(player_name):
                self.handler.logger.info(
                    f"{message_info.nickname} 尝试播放歌手歌单，但 {player_name} 正在播放"
                )
                return {"error": f"{player_name} 正在播放歌单，请等待"}

        self.soul_handler.ensure_mic_active()
        info_manager.player_name = message_info.nickname
        info = self.play_singer(query)
        return info

    def select_singer_tab(self):
        """Select the 'Singer' tab in search results"""
        try:
            # Try to find singer tab first
            singer_tab = self.handler.try_find_element("singer_tab")
            if not singer_tab:
                # If not found, scroll music_tabs to find it
                music_tabs = self.handler.wait_for_element_clickable("music_tabs")
                if not music_tabs:
                    self.handler.logger.error("Failed to find music tabs")
                    return False

                # Get size and location for scrolling
                size = music_tabs.size
                location = music_tabs.location

                # Scroll to right
                self.handler.driver.swipe(
                    location["x"] + 200,  # Start from left
                    location["y"] + size["height"] // 2,
                    location["x"] + size["width"] - 10,  # End at right
                    location["y"] + size["height"] // 2,
                    1000,
                )

                # Try to find singer tab again
                singer_tab = self.handler.try_find_element("singer_tab")
                if not singer_tab:
                    self.handler.logger.error(
                        "Failed to find singer tab after scrolling"
                    )
                    return False

            singer_tab.click()
            self.handler.logger.info("Selected singer tab")
            return True

        except Exception as e:
            self.handler.logger.error(
                f"Error selecting singer tab: {traceback.format_exc()}"
            )
            return False

    def play_singer(self, query: str):
        from_key = self.handler.query_music(query)
        if not from_key:
            return {
                "error": f"Failed to query singer {query}",
            }

        play_singer = None
        singer_name = 'Unknown'
        if from_key == "home_nav":
            key, element = self.handler.wait_for_any_element(["first_song", "not_found"])
            if not key or key == "not_found":
                self.handler.logger.error(f'not found singer with query {query}')
                return {
                    'error': f'not found singer with query {query}',
                }

            if play_singer := self.handler.try_find_element("play_singer_1"):
                if singer_name := self.handler.try_get_attribute(play_singer, "content-desc"):
                    singer_name = singer_name.split(': ')[1]
                    singer_name = singer_name.split('的歌曲')[0]
            elif play_singer := self.handler.try_find_element("play_singer"):
                if singer_name_element := self.handler.try_find_element("singer_name"):
                    singer_name = singer_name_element.text

        if play_singer:
            play_singer.click()
            self.handler.logger.info("Selected singer play")
        else:
            self.select_singer_tab()
            key, element = self.handler.wait_for_any_element(["singer_result", "not_found"])
            if not key or key == "not_found":
                self.handler.logger.error(f'not found singer with query {query}')
                return {
                    'error': f'not found singer with query {query}',
                }
            singer_result = element

            singer_result.click()
            self.handler.logger.info("Selected singer result")
            singer_name = singer_result.text

            play_button = self.handler.wait_for_element_clickable("play_all")
            if not play_button:
                self.handler.logger.error("Cannot find play singer button")
                return {"error": "Failed to find play button"}
            play_button.click()

            self.handler.logger.info("Clicked play singer result")

        # Get playlist info from UI instead of ADB
        playing_info = self.handler.get_playlist_info()
        playlist_text, first_song, error = get_playlist_text_and_first_song(playing_info)
        if error:
            self.handler.logger.warning(f"Failed to read singer playlist after playback started: {error}")
            playlist_text = singer_name
            first_song = None

        first_song_title = first_song.split(" - ")[0].strip() if first_song else ""
        topic = first_song_title or singer_name

        self.handler.list_mode = "singer"

        # 使用 title_manager 和 topic_manager 管理标题和话题
        self.title_manager.set_next_title(singer_name)
        self.topic_manager.change_topic(topic)

        # 存储完整的歌单名称到 InfoManager
        self.info_manager.current_playlist_name = singer_name

        return {"playlist": playlist_text}
