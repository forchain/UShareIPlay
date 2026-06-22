from typing import Optional

from selenium.common import StaleElementReferenceException

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.helpers.playlist_info import get_playlist_text_and_first_song
from ushareiplay.helpers.song_release import QQMusicSongReleaseLookup, parse_release_date
from ushareiplay.handlers.qq_music_handler import QQMusicHandler
from ushareiplay.handlers.soul_handler import SoulHandler
from ushareiplay.managers.title_manager import TitleManager
from ushareiplay.managers.topic_manager import TopicManager

class RadioCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.music_handler: QQMusicHandler = controller.music_handler
        self.soul_handler: SoulHandler = controller.soul_handler
        self.title_manager = TitleManager.instance()
        self.topic_manager = TopicManager.instance()
        self.song_release_lookup = QQMusicSongReleaseLookup()

        # 延迟初始化 InfoManager
        self._info_manager = None

    @property
    def info_manager(self):
        """延迟获取 InfoManager 实例"""
        if self._info_manager is None:
            from ushareiplay.managers.info_manager import InfoManager
            self._info_manager = InfoManager.instance()
        return self._info_manager

    async def process(self, message_info, parameters):
        if not parameters:
            return self._handle_collection(message_info)

        # 添加播放器保护逻辑
        player_name = self.info_manager.player_name
        # 排除系统用户 Joyer 和 Timer
        if player_name and player_name != message_info.nickname and player_name not in ["Joyer", "Timer", "Outlier",
                                                                                        "Chainer"]:
            # 检查之前的播放者是否还在线
            if self.info_manager.is_user_online(player_name):
                self.music_handler.logger.info(f"{message_info.nickname} 尝试播放电台，但 {player_name} 正在播放")
                return {'error': f'{player_name} 正在播放歌单，请等待'}

        keyword = parameters[0].lower()
        try:
            if keyword == "guess":
                return self._handle_guess_like(message_info)
            if keyword == "daily":
                return self._handle_daily_30(message_info)
            if keyword == "collection":
                return self._handle_collection(message_info)
            if keyword == "sleep":
                return self._handle_sleep_healing(message_info)
            if keyword == "radar":
                return self._handle_radar(message_info)
            return {"error": f"Unsupported radio keyword: {keyword}"}
        except Exception as exc:
            return self._report_error(f"Radio command failed for keyword {keyword}: {exc}")

    def _report_error(self, message: str):
        self.music_handler.logger.error(message)
        self.soul_handler.send_message(message)
        return {"error": message}

    def _navigate_home(self):
        if not self.music_handler.switch_to_app():
            return self._report_error("Cannot switch to QQ Music")
        if not self.music_handler.navigate_to_home():
            return self._report_error("Failed to navigate to home in QQ Music")
        return None

    def _switch_back_to_soul(self):
        if not self.soul_handler.switch_to_app():
            return self._report_error("Failed to switch back to Soul app")
        return None

    def _set_room_context(self, room_name: str, topic_text: Optional[str] = None):
        title_result = self.title_manager.set_next_title(room_name)
        if "error" in title_result:
            return self._report_error(title_result["error"])
        if topic_value := topic_text.strip() if topic_text else None:
            if '-' in topic_value:
                topic_value = topic_value.split("-")[0].strip()
            topic_result = self.topic_manager.change_topic(topic_value)
            if "error" in topic_result:
                return self._report_error(topic_result["error"])
        return None

    def _extract_primary_topic(self, raw_topic: Optional[str]) -> Optional[str]:
        if not raw_topic:
            return None
        parts = [segment.strip() for segment in raw_topic.split("-") if segment.strip()]
        if not parts:
            cleaned_topic = raw_topic.strip()
            return cleaned_topic or None
        return parts[0]

    def _old_song_filter_config(self) -> dict:
        return (self.controller.config or {}).get("old_song_filter", {})

    def _song_release_date(self, song_text: Optional[str]):
        if not song_text:
            return None
        try:
            return parse_release_date(self.song_release_lookup.get_release_date(song_text))
        except Exception as exc:
            self.music_handler.logger.warning(
                f"Failed to query song release date for {song_text}: {exc}"
            )
            return None

    def _is_old_song(self, song_text: Optional[str]) -> bool:
        config = self._old_song_filter_config()
        if not config.get("enabled", True):
            return False

        cutoff = parse_release_date(config.get("cutoff_date") or "2010-01-01")
        if not cutoff or not song_text:
            return False

        release_date = self._song_release_date(song_text)
        if not release_date:
            self.music_handler.logger.info(
                f"Release date unknown for {song_text}, accepting recommendation"
            )
            return False

        is_old = release_date < cutoff
        if is_old:
            self.music_handler.logger.info(
                f"First radio song is old ({release_date} < {cutoff}): {song_text}"
            )
        return is_old

    def _refresh_collection_radio(self):
        home_nav = self.music_handler.wait_for_element_clickable("home_nav")
        if not home_nav:
            return self._report_error("Failed to find home navigation while refreshing radio")
        home_nav.click()

        play_button = self.music_handler.wait_for_element_clickable("play_collection")
        if not play_button:
            return self._report_error("Failed to find collection play button after refresh")
        collection_topic = self.music_handler.wait_for_element("collection_topic")
        if not collection_topic:
            return self._report_error("Failed to locate collection radio topic after refresh")
        return play_button, collection_topic

    def _read_collection_topic_text(self, collection_topic, max_attempts: int = 3) -> Optional[str]:
        for attempt in range(1, max_attempts + 1):
            try:
                return self._extract_primary_topic(collection_topic.text)
            except StaleElementReferenceException:
                self.music_handler.logger.warning(
                    f"Radio collection topic element stale, refinding topic ({attempt}/{max_attempts})"
                )
                collection_topic = self.music_handler.wait_for_element("collection_topic")
                if not collection_topic:
                    return None
        return None

    def _handle_guess_like(self, message_info):
        error = self._navigate_home()
        if error:
            return error
        guess_title = self.music_handler.wait_for_element_clickable("guess_title")
        guess_topic = self.music_handler.wait_for_element("guess_topic")
        if not guess_title or not guess_topic:
            return self._report_error("Failed to locate guess like radio elements")
        guess_title_text = guess_title.text
        guess_topic_text = self._extract_primary_topic(guess_topic.text)
        guess_title.click()
        playlist_info = self.music_handler.get_playlist_info()
        playlist_text, _, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            return self._report_error(error)
        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(guess_title_text, guess_topic_text)
        if error:
            return error
        # 更新播放器名称
        self.info_manager.player_name = message_info.nickname
        # 设置歌单类型和名称
        self.music_handler.list_mode = 'radio'
        self.info_manager.current_playlist_name = guess_title_text
        return {"playlist": playlist_text}

    def _handle_daily_30(self, message_info):
        error = self._navigate_home()
        if error:
            return error
        daily_title = self.music_handler.wait_for_element_clickable("daily_title")
        daily_topic = self.music_handler.wait_for_element("daily_topic")
        if not daily_title or not daily_topic:
            return self._report_error("Failed to locate daily radio elements")
        daily_title_text = daily_title.text
        daily_topic_text = self._extract_primary_topic(daily_topic.text)
        daily_title.click()
        play_all = self.music_handler.wait_for_element_clickable("play_all")
        if not play_all:
            return self._report_error("Failed to locate play all button")
        play_all.click()

        # Prefer the first song title in the playing queue as the room topic.
        # Fallback to the UI-provided daily_topic_text if queue parsing fails.
        topic_text = daily_topic_text
        playlist_info = self.music_handler.get_playlist_info()
        playlist_text, first_line, error = get_playlist_text_and_first_song(playlist_info)
        if not error and first_line:
            topic_text = first_line.split(" - ")[0].strip() or topic_text

        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(daily_title_text, topic_text)
        if error:
            return error
        # 更新播放器名称
        self.info_manager.player_name = message_info.nickname
        # 设置歌单类型和名称
        self.music_handler.list_mode = 'radio'
        self.info_manager.current_playlist_name = daily_title_text
        return {"playlist": playlist_text or daily_title_text}

    def _handle_collection(self, message_info):
        error = self._navigate_home()
        if error:
            return error
        key, element = self.music_handler.wait_for_any_element(["pause_collection", "play_collection"])
        if key == "pause_collection":
            self.music_handler.logger.info("正在播放精选，刷新")
            home_nav = self.music_handler.wait_for_element_clickable("home_nav")
            home_nav.click()
            play_button = self.music_handler.wait_for_element_clickable("play_collection")
        elif key == "play_collection":
            play_button = element
        else:
            return self._report_error("Failed to find collection play button")
        if not play_button:
            return self._report_error("Failed to find collection play button")

        collection_title = self.music_handler.wait_for_element_clickable("collection_title")
        collection_topic = self.music_handler.wait_for_element("collection_topic")
        if not collection_title or not collection_topic:
            return self._report_error("Failed to locate collection radio elements")
        collection_title_text = self.soul_handler.try_get_attribute(collection_title, 'content-desc') or "Unknown"
        splitter = '音频按钮'
        # Truncate text after splitter if present
        if splitter in collection_title_text:
            collection_title_text = collection_title_text.split(splitter)[0]
        splitter = '「'
        # Truncate text after splitter if present
        if splitter in collection_title_text:
            collection_title_text = collection_title_text.split(splitter)[1]
        splitter = '」'
        # Truncate text after splitter if present
        if splitter in collection_title_text:
            collection_title_text = collection_title_text.split(splitter)[0]

        filter_config = self._old_song_filter_config()
        max_refreshes = int(filter_config.get("radio_max_refreshes", 5))
        refresh_count = 0
        while True:
            collection_topic_text = self._read_collection_topic_text(collection_topic)
            if not collection_topic_text:
                return self._report_error("Failed to read collection radio topic")
            release_date = self._song_release_date(collection_topic_text)
            self.music_handler.logger.info(
                f"Radio recommendation candidate: {collection_topic_text}, release_date={release_date or 'unknown'}"
            )
            cutoff = parse_release_date(filter_config.get("cutoff_date") or "2010-01-01")
            is_old = bool(release_date and cutoff and release_date < cutoff)
            if not is_old:
                break
            if refresh_count >= max_refreshes:
                self.music_handler.logger.warning(
                    f"Radio recommendation still old after {refresh_count} refreshes, accepting: {collection_topic_text}"
                )
                break
            refresh_count += 1
            self.music_handler.logger.info(
                f"Radio recommendation is old ({release_date} < {cutoff}): {collection_topic_text}; refreshing recommendation ({refresh_count}/{max_refreshes})"
            )
            refresh_result = self._refresh_collection_radio()
            if isinstance(refresh_result, dict) and "error" in refresh_result:
                return refresh_result
            play_button, collection_topic = refresh_result

        play_button.click()
        playlist_info = self.music_handler.get_playlist_info()
        playlist_text, first_song, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            return self._report_error(error)

        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(collection_title_text, collection_topic_text)
        if error:
            return error
        # 更新播放器名称
        self.info_manager.player_name = message_info.nickname
        # 设置歌单类型和名称
        self.music_handler.list_mode = 'radio'
        self.info_manager.current_playlist_name = collection_title_text
        return {"playlist": playlist_text}

    def _handle_sleep_healing(self, message_info):
        error = self._navigate_home()
        if error:
            return error

        healing_room_name = "音乐疗愈"
        _, healing_tab, _ = self.music_handler.scroll_container_until_element(
            "home_tab_label",
            "home_tab_strip",
            "left",
            "text",
            "疗愈",
            max_swipes=20,
        )
        if not healing_tab:
            return self._report_error("Failed to scroll home tabs to 疗愈 column")
        healing_tab.click()
        self.music_handler.logger.info("Clicked 疗愈 tab after scrolling home tab strip")

        play_healing = self.music_handler.wait_for_element_clickable("play_healing")
        if not play_healing:
            return self._report_error("Failed to find healing play button")
        play_healing.click()
        playlist_info = self.music_handler.get_playlist_info()
        playlist_text, first_song, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            return self._report_error(error)
        if not self.music_handler.navigate_to_home():
            return self._report_error("Failed to navigate to home")
        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(healing_room_name, first_song or None)
        if error:
            return error
        # 更新播放器名称
        self.info_manager.player_name = message_info.nickname
        # 设置歌单类型和名称
        self.music_handler.list_mode = 'radio'
        self.info_manager.current_playlist_name = healing_room_name
        return {"playlist": playlist_text}

    def _handle_radar(self, message_info):
        """Handle radar radio station"""
        error = self._navigate_home()
        if error:
            return error

        # 点击 radar 导航
        radar_nav = self.music_handler.try_find_element('radar_nav', log=False)
        if not radar_nav:
            return self._report_error("Cannot find radar_nav")

        radar_nav.click()
        self.music_handler.logger.info("Clicked radar navigation button")

        # 获取 radar 歌曲和歌手信息
        radar_song = self.music_handler.wait_for_element_clickable('radar_song')
        radar_singer = self.music_handler.wait_for_element_clickable('radar_singer')

        if not radar_song or not radar_singer:
            return self._report_error("Failed to locate radar song or singer elements")

        song_text = radar_song.text
        singer_text = radar_singer.text
        playlist_info = self.music_handler.get_playlist_info()
        playlist_text, _, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            return self._report_error(error)

        # 切换回 Soul
        error = self._switch_back_to_soul()
        if error:
            return error

        # 设置房间标题和话题
        error = self._set_room_context("O Radio", song_text)
        if error:
            return error

        # 更新播放器名称
        self.info_manager.player_name = message_info.nickname
        # 设置歌单类型和名称
        self.music_handler.list_mode = 'radio'
        self.info_manager.current_playlist_name = "O Radio"

        return {
            "playlist": playlist_text,
            "song": song_text,
            "singer": singer_text,
            "album": ""
        }
