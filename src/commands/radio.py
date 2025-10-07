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

    async def process(self, message_info, parameters):
        if not parameters:
            return {"error": "Missing radio keyword"}

        keyword = parameters[0].lower()
        try:
            if keyword == "guess":
                return self._handle_guess_like()
            if keyword == "daily":
                return self._handle_daily_30()
            if keyword == "collection":
                return self._handle_collection()
            if keyword == "sleep":
                return self._handle_sleep_healing()
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

    def _send_playlist_message(self, playlist_text: str):
        result = self.soul_handler.send_message(playlist_text)
        if isinstance(result, dict) and "error" in result:
            return self._report_error(result["error"])
        return None

    def _handle_guess_like(self):
        error = self._navigate_home()
        if error:
            return error
        guess_title = self.music_handler.wait_for_element_clickable_plus("guess_title")
        guess_topic = self.music_handler.wait_for_element_plus("guess_topic")
        if not guess_title or not guess_topic:
            return self._report_error("Failed to locate guess like radio elements")
        guess_title_text = guess_topic.text
        guess_topic_text = guess_topic.text
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
        error = self._send_playlist_message(playlist_text)
        if error:
            return error
        return {"playlist": playlist_text}

    def _handle_daily_30(self):
        error = self._navigate_home()
        if error:
            return error
        daily_title = self.music_handler.wait_for_element_clickable_plus("daily_title")
        daily_topic = self.music_handler.wait_for_element_plus("daily_topic")
        if not daily_title or not daily_topic:
            return self._report_error("Failed to locate daily radio elements")
        daily_title_text = daily_title.text
        daily_topic_text = daily_topic.text
        daily_title.click()
        playlist_text, error = self._ensure_playlist_text()
        if error:
            return error
        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(daily_title_text, daily_topic_text)
        if error:
            return error
        error = self._send_playlist_message(playlist_text)
        if error:
            return error
        return {"playlist": playlist_text}

    def _handle_collection(self):
        error = self._navigate_home()
        if error:
            return error
        collection_title = self.music_handler.wait_for_element_clickable_plus("collection_title")
        collection_topic = self.music_handler.wait_for_element_plus("collection_topic")
        if not collection_title or not collection_topic:
            return self._report_error("Failed to locate collection radio elements")
        collection_title_text = collection_title.text
        collection_topic_text = collection_topic.text
        collection_title.click()
        play_button = self.music_handler.wait_for_element_clickable_plus("play_collection")
        if not play_button:
            return self._report_error("Failed to find collection play button")
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
        error = self._send_playlist_message(playlist_text)
        if error:
            return error
        return {"playlist": playlist_text}

    def _handle_sleep_healing(self):
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
        recommend_tab = self.music_handler.wait_for_element_clickable_plus("recommend_tab")
        if not recommend_tab:
            return self._report_error("Failed to switch back to recommend tab")
        recommend_tab.click()
        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(healing_room_name, first_song or None)
        if error:
            return error
        error = self._send_playlist_message(playlist_text)
        if error:
            return error
        return {"playlist": playlist_text}
