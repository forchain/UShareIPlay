from ushareiplay.core.base_command import BaseCommand
from ushareiplay.helpers.playlist_info import get_playlist_text_and_first_song


class SingerCommand(BaseCommand):
    playback_muting = True
    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        query = " ".join(parameters)

        # 歌单守护检查：若当前播放者不是管理员且仍在房间（含分身），阻断切歌
        config = getattr(self.controller, "config", None)
        protection_error = await self.playlist_adoption.guard_switch(
            message_info.nickname, config=config
        )
        if protection_error:
            self.handler.logger.info(
                f"{message_info.nickname} 尝试播放歌手歌单，但 {self.info_manager.player_name} 正在播放"
            )
            return protection_error

        info = self.play_singer(query, message_info.nickname)
        return info

    def play_singer(self, query: str, requester=None):
        from_key = self.handler.query_music(query)
        if not from_key:
            return {
                "error": f"Failed to query singer {query}",
            }

        play_singer = None
        singer_name = 'Unknown'
        if from_key == "home_nav":
            key, element = self.handler.element_finder.wait_for_any_element(["music_tabs", "not_found"], timeout=5)
            if key and key != "not_found":
                if play_singer_elem := self.handler.element_finder.try_find_element("play_singer_1"):
                    play_singer = play_singer_elem
                    if singer_name_attr := self.handler.element_finder.try_get_attribute(play_singer, "content-desc"):
                        singer_name = singer_name_attr.split(': ')[1]
                        singer_name = singer_name.split('的歌曲')[0]
                elif play_singer_elem := self.handler.element_finder.try_find_element("play_singer"):
                    play_singer = play_singer_elem
                    if singer_name_element := self.handler.element_finder.try_find_element("singer_name"):
                        singer_name = singer_name_element.text

        if play_singer:
            play_singer.click()
            self.handler.logger.info("Selected singer play")
        else:
            if not self.music_manager.select_tab("singer"):
                self.handler.logger.error(f"Failed to select singer tab with query {query}")
                return {
                    'error': f'not found singer with query {query}',
                }
            key, element = self.handler.element_finder.wait_for_any_element(["singer_result", "not_found"])
            if not key or key == "not_found":
                self.handler.logger.error(f'not found singer with query {query}')
                return {
                    'error': f'not found singer with query {query}',
                }
            singer_result = element

            singer_result.click()
            self.handler.logger.info("Selected singer result")
            singer_name = singer_result.text

            play_button = self.handler.element_finder.wait_for_element_clickable("play_all")
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

        # 播放队列首行是「歌名 - 歌手」，话题归一化交给 PlaylistAdoption
        self.playlist_adoption.adopt(
            requester=requester,
            mode="singer",
            title=singer_name,
            topic=first_song or singer_name,
            playlist=singer_name,
        )

        return {"playlist": playlist_text}
