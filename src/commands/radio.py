from typing import Optional

from ..core.base_command import BaseCommand
from ..handlers.qq_music_handler import QQMusicHandler
from ..handlers.soul_handler import SoulHandler
from ..managers.title_manager import TitleManager
from ..managers.topic_manager import TopicManager

command = None


def create_command(controller):
    radio_command = RadioCommand(controller)
    controller.radio_command = radio_command
    return radio_command


class RadioCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.music_handler: QQMusicHandler = controller.music_handler
        self.soul_handler: SoulHandler = controller.soul_handler
        self.title_manager = TitleManager.instance()
        self.topic_manager = TopicManager.instance()

        # 延迟初始化 InfoManager
        self._info_manager = None

    @property
    def info_manager(self):
        """延迟获取 InfoManager 实例"""
        if self._info_manager is None:
            from ..managers.info_manager import InfoManager
            self._info_manager = InfoManager.instance()
        return self._info_manager

    async def process(self, message_info, parameters):
        if not parameters:
            return self._handle_collection(message_info)

        # 添加播放器保护逻辑
        player_name = self.info_manager.player_name
        # 排除系统用户 Joyer 和 Timer
        if player_name and player_name != message_info.nickname and player_name not in ["Joyer", "Timer", "Outlier"]:
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

    def _ensure_playlist_text(self):
        playlist_info = self.music_handler.get_playlist_info()
        if "error" in playlist_info:
            return None, self._report_error(playlist_info["error"])
        playlist_text = playlist_info.get("playlist", "").strip()
        if not playlist_text:
            return None, self._report_error("Playlist content is empty")
        return playlist_text, None

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
        if topic_text:
            topic_value = topic_text.strip()
            if topic_value:
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

    def _handle_guess_like(self, message_info):
        error = self._navigate_home()
        if error:
            return error
        guess_title = self.music_handler.wait_for_element_clickable_plus("guess_title")
        guess_topic = self.music_handler.wait_for_element_plus("guess_topic")
        if not guess_title or not guess_topic:
            return self._report_error("Failed to locate guess like radio elements")
        guess_title_text = guess_title.text
        guess_topic_text = self._extract_primary_topic(guess_topic.text)
        guess_title.click()
        playlist_text, error = self._ensure_playlist_text()
        if error:
            return error
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
        daily_title = self.music_handler.wait_for_element_clickable_plus("daily_title")
        daily_topic = self.music_handler.wait_for_element_plus("daily_topic")
        if not daily_title or not daily_topic:
            return self._report_error("Failed to locate daily radio elements")
        daily_title_text = daily_title.text
        daily_topic_text = self._extract_primary_topic(daily_topic.text)
        daily_title.click()
        play_all = self.music_handler.wait_for_element_clickable_plus("play_all")
        if not play_all:
            return self._report_error("Failed to locate play all button")
        play_all.click()
        playlist_text, error = self._ensure_playlist_text()
        if error:
            return error
        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(daily_title_text, daily_topic_text)
        if error:
            return error
        # 更新播放器名称
        self.info_manager.player_name = message_info.nickname
        # 设置歌单类型和名称
        self.music_handler.list_mode = 'radio'
        self.info_manager.current_playlist_name = daily_title_text
        return {"playlist": playlist_text}

    def _handle_collection(self, message_info):
        error = self._navigate_home()
        if error:
            return error
        key, element = self.music_handler.wait_for_any_element_plus(["play_collection", "pause_collection"])
        if key == "pause_collection":
            self.music_handler.logger.info("正在播放精选，刷新")
            home_nav = self.music_handler.wait_for_element_clickable_plus("home_nav")
            home_nav.click()
            play_button = self.music_handler.wait_for_element_clickable_plus("play_collection")
        elif key == "play_collection":
            play_button = element
        else:
            return self._report_error("Failed to find collection play button")
        if not play_button:
            return self._report_error("Failed to find collection play button")

        collection_title = self.music_handler.wait_for_element_clickable_plus("collection_title")
        collection_topic = self.music_handler.wait_for_element_plus("collection_topic")
        if not collection_title or not collection_topic:
            return self._report_error("Failed to locate collection radio elements")
        collection_title_text = self.soul_handler.try_get_attribute(collection_title, 'content-desc') or "Unknown"
        splitter = '音频按钮'
        # Truncate text after splitter if present
        if splitter in collection_title_text:
            collection_title_text = collection_title_text.split(splitter)[0]
        collection_topic_text = self._extract_primary_topic(collection_topic.text)
        play_button.click()
        playlist_text, error = self._ensure_playlist_text()
        if error:
            return error
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
        healing_tab = self.music_handler.wait_for_element_clickable_plus("healing_tab")
        if not healing_tab:
            return self._report_error("Failed to locate healing tab")
        healing_room_name = healing_tab.text
        healing_tab.click()
        play_healing = self.music_handler.wait_for_element_clickable_plus("play_healing")
        if not play_healing:
            return self._report_error("Failed to find healing play button")
        play_healing.click()
        playlist_info = self.music_handler.get_playlist_info()
        if "error" in playlist_info:
            return self._report_error(playlist_info["error"])
        playlist_text = playlist_info.get("playlist", "").strip()
        if not playlist_text:
            return self._report_error("Playlist content is empty")
        first_song = playlist_text.splitlines()[0] if playlist_text else ""
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
        radar_nav = self.music_handler.try_find_element_plus('radar_nav', log=False)
        if not radar_nav:
            return self._report_error("Cannot find radar_nav")

        radar_nav.click()
        self.music_handler.logger.info("Clicked radar navigation button")

        # 获取 radar 歌曲和歌手信息
        radar_song = self.music_handler.wait_for_element_clickable_plus('radar_song')
        radar_singer = self.music_handler.wait_for_element_clickable_plus('radar_singer')

        if not radar_song or not radar_singer:
            return self._report_error("Failed to locate radar song or singer elements")

        song_text = radar_song.text
        singer_text = radar_singer.text

        playlist_text, error = self._ensure_playlist_text()
        if error:
            return error

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
