"""Radio playback workflow module.

Owns radio selection, navigation, metadata parsing, old-song policy,
room context updates, and return-to-Soul behavior. ``RadioCommand`` is a
thin command adapter that delegates here.
"""

from __future__ import annotations

from typing import Any, Optional


# System users exempt from the player-protection guard. Mirrors the prior
# inline constant in ``RadioCommand``; centralized so the policy is local.
RADIO_PLAYER_EXEMPT_NICKNAMES = ("Joyer", "Timer", "Outlier", "Chainer")


class RadioWorkflow:
    """Deep radio workflow.

    All radio-specific orchestration lives here. The command layer is a
    thin adapter; tests can drive the workflow directly with a deterministic
    QQ Music UI adapter and a fake info/title/topic/player context.
    """

    def __init__(
        self,
        *,
        music_ui: Any,
        soul_ui: Any,
        info_manager: Any,
        title_manager: Any,
        topic_manager: Any,
        song_release_lookup: Any,
        config: dict | None = None,
    ):
        self._music = music_ui
        self._soul = soul_ui
        self._info = info_manager
        self._title = title_manager
        self._topic = topic_manager
        self._song_release_lookup = song_release_lookup
        self._config = config or {}

    # ------------------------------------------------------------------
    # Public entry point.
    # ------------------------------------------------------------------

    def dispatch(self, message_info, parameters) -> dict:
        """Dispatch a radio command to the right mode handler."""
        if not parameters:
            return self._handle_collection(message_info)

        player_name = self._info.player_name
        if (
            player_name
            and player_name != message_info.nickname
            and player_name not in RADIO_PLAYER_EXEMPT_NICKNAMES
            and self._info.is_user_online(player_name)
        ):
            self._music.logger.info(
                f"{message_info.nickname} 尝试播放电台，但 {player_name} 正在播放"
            )
            return {"error": f"{player_name} 正在播放歌单，请等待"}

        keyword = parameters[0].lower()
        handlers = {
            "guess": self._handle_guess_like,
            "daily": self._handle_daily_30,
            "collection": self._handle_collection,
            "sleep": self._handle_sleep_healing,
            "radar": self._handle_radar,
        }
        if keyword not in handlers:
            return {"error": f"Unsupported radio keyword: {keyword}"}
        try:
            return handlers[keyword](message_info)
        except Exception as exc:
            return self._report_error(f"Radio command failed for keyword {keyword}: {exc}")

    # ------------------------------------------------------------------
    # Helpers (navigation, room context, policy).
    # ------------------------------------------------------------------

    def _report_error(self, message: str) -> dict:
        self._music.logger.error(message)
        return {"error": message}

    def _navigate_home(self) -> Optional[dict]:
        if not self._music.key_actions.switch_to_app():
            return self._report_error("Cannot switch to QQ Music")
        if not self._music.navigate_to_home():
            return self._report_error("Failed to navigate to home in QQ Music")
        return None

    def _switch_back_to_soul(self) -> Optional[dict]:
        if not self._soul.key_actions.switch_to_app():
            return self._report_error("Failed to switch back to Soul app")
        return None

    def _set_room_context(
        self, room_name: str, topic_text: Optional[str] = None
    ) -> Optional[dict]:
        title_result = self._title.set_next_title(room_name)
        if "error" in title_result:
            return self._report_error(title_result["error"])
        if topic_value := (topic_text.strip() if topic_text else None):
            if "-" in topic_value:
                topic_value = topic_value.split("-")[0].strip()
            topic_result = self._topic.change_topic(topic_value)
            if "error" in topic_result:
                return self._report_error(topic_result["error"])
        return None

    @staticmethod
    def extract_primary_topic(raw_topic: Optional[str]) -> Optional[str]:
        if not raw_topic:
            return None
        parts = [segment.strip() for segment in raw_topic.split("-") if segment.strip()]
        if not parts:
            cleaned_topic = raw_topic.strip()
            return cleaned_topic or None
        return parts[0]

    def _old_song_filter_config(self) -> dict:
        return self._config.get("old_song_filter", {})

    def _song_release_date(self, song_text: Optional[str]):
        if not song_text:
            return None
        from ushareiplay.helpers.song_release import parse_release_date
        try:
            return parse_release_date(self._song_release_lookup.get_release_date(song_text))
        except Exception as exc:
            self._music.logger.warning(
                f"Failed to query song release date for {song_text}: {exc}"
            )
            return None

    def _publish_playback(self, message_info, playlist_name: str) -> None:
        """Update mutable playback state on the success path."""
        self._info.player_name = message_info.nickname
        self._music.list_mode = "radio"
        self._info.current_playlist_name = playlist_name

    # ------------------------------------------------------------------
    # Mode handlers. Each owns the full chain:
    #   navigate -> find UI elements -> click -> read playlist
    #   -> switch back to Soul -> set room context -> publish state
    # ------------------------------------------------------------------

    def _handle_guess_like(self, message_info) -> dict:
        from ushareiplay.helpers.playlist_info import (
            get_playlist_text_and_first_song,
        )

        error = self._navigate_home()
        if error:
            return error
        guess_title = self._music.element_finder.wait_for_element_clickable("guess_title")
        guess_topic = self._music.element_finder.wait_for_element("guess_topic")
        if not guess_title or not guess_topic:
            return self._report_error("Failed to locate guess like radio elements")
        guess_title_text = guess_title.text
        guess_topic_text = self.extract_primary_topic(guess_topic.text)
        guess_title.click()
        playlist_info = self._music.get_playlist_info()
        playlist_text, _, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            self._music.logger.warning(
                f"Failed to read guess-like playlist after playback started: {error}"
            )
            playlist_text = guess_title_text
        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(guess_title_text, guess_topic_text)
        if error:
            return error
        self._publish_playback(message_info, guess_title_text)
        return {"playlist": playlist_text}

    def _handle_daily_30(self, message_info) -> dict:
        from ushareiplay.helpers.playlist_info import (
            get_playlist_text_and_first_song,
        )

        error = self._navigate_home()
        if error:
            return error
        daily_title = self._music.element_finder.wait_for_element_clickable("daily_title")
        daily_topic = self._music.element_finder.wait_for_element("daily_topic")
        if not daily_title or not daily_topic:
            return self._report_error("Failed to locate daily radio elements")
        daily_title_text = daily_title.text
        daily_topic_text = self.extract_primary_topic(daily_topic.text)
        daily_title.click()
        play_all = self._music.element_finder.wait_for_element_clickable("play_all")
        if not play_all:
            return self._report_error("Failed to locate play all button")
        play_all.click()

        topic_text = daily_topic_text
        playlist_info = self._music.get_playlist_info()
        playlist_text, first_line, error = get_playlist_text_and_first_song(playlist_info)
        if not error and first_line:
            topic_text = first_line.split(" - ")[0].strip() or topic_text
        elif error:
            self._music.logger.warning(
                f"Failed to read daily radio playlist after playback started: {error}"
            )

        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(daily_title_text, topic_text)
        if error:
            return error
        self._publish_playback(message_info, daily_title_text)
        return {"playlist": playlist_text or daily_title_text}

    def _handle_collection(self, message_info) -> dict:
        from ushareiplay.helpers.playlist_info import (
            get_playlist_text_and_first_song,
        )
        from selenium.common import StaleElementReferenceException

        error = self._navigate_home()
        if error:
            return error
        key, element = self._music.element_finder.wait_for_any_element(
            ["pause_collection", "play_collection"]
        )
        if key == "pause_collection":
            self._music.logger.info("正在播放精选，刷新")
            home_nav = self._music.element_finder.wait_for_element_clickable("home_nav")
            home_nav.click()
            play_button = self._music.element_finder.wait_for_element_clickable("play_collection")
        elif key == "play_collection":
            play_button = element
        else:
            return self._report_error("Failed to find collection play button")
        if not play_button:
            return self._report_error("Failed to find collection play button")

        collection_title = self._music.element_finder.wait_for_element_clickable("collection_title")
        collection_topic = self._music.element_finder.wait_for_element("collection_topic")
        if not collection_title or not collection_topic:
            return self._report_error("Failed to locate collection radio elements")
        collection_title_text = (
            self._soul.element_finder.try_get_attribute(collection_title, "content-desc")
            or "Unknown"
        )
        for splitter in ("音频按钮", "「", "」"):
            if splitter in collection_title_text:
                collection_title_text = collection_title_text.split(splitter)[
                    1 if splitter == "「" else 0
                ]

        # Old-song filter loop.
        filter_config = self._old_song_filter_config()
        max_refreshes = int(filter_config.get("radio_max_refreshes", 5))
        refresh_count = 0
        from ushareiplay.helpers.song_release import parse_release_date

        cutoff = parse_release_date(filter_config.get("cutoff_date") or "2000-01-01")
        while True:
            collection_topic_text = self._read_collection_topic_text(
                collection_topic, StaleElementReferenceException
            )
            if not collection_topic_text:
                return self._report_error("Failed to read collection radio topic")
            release_date = self._song_release_date(collection_topic_text)
            self._music.logger.info(
                f"Radio recommendation candidate: {collection_topic_text}, "
                f"release_date={release_date or 'unknown'}"
            )
            is_old = bool(release_date and cutoff and release_date < cutoff)
            if not is_old:
                break
            if refresh_count >= max_refreshes:
                self._music.logger.warning(
                    f"Radio recommendation still old after {refresh_count} refreshes, "
                    f"accepting: {collection_topic_text}"
                )
                break
            refresh_count += 1
            self._music.logger.info(
                f"Radio recommendation is old ({release_date} < {cutoff}): "
                f"{collection_topic_text}; refreshing recommendation "
                f"({refresh_count}/{max_refreshes})"
            )
            refresh_result = self._refresh_collection_radio()
            if isinstance(refresh_result, dict) and "error" in refresh_result:
                return refresh_result
            play_button, collection_topic = refresh_result

        play_button.click()
        playlist_info = self._music.get_playlist_info()
        playlist_text, first_song, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            self._music.logger.warning(
                f"Failed to read collection playlist after playback started: {error}"
            )
            playlist_text = collection_title_text
            first_song = None
        first_song_title = first_song.split(" - ")[0].strip() if first_song else ""
        room_title_text = first_song_title or collection_title_text

        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(room_title_text, collection_title_text)
        if error:
            return error
        self._publish_playback(message_info, collection_title_text)
        return {"playlist": playlist_text}

    def _read_collection_topic_text(self, collection_topic, stale_exception, max_attempts: int = 3):
        for attempt in range(1, max_attempts + 1):
            try:
                return self.extract_primary_topic(collection_topic.text)
            except stale_exception:
                self._music.logger.warning(
                    f"Radio collection topic element stale, refinding topic "
                    f"({attempt}/{max_attempts})"
                )
                collection_topic = self._music.element_finder.wait_for_element("collection_topic")
                if not collection_topic:
                    return None
        return None

    def _refresh_collection_radio(self):
        home_nav = self._music.element_finder.wait_for_element_clickable("home_nav")
        if not home_nav:
            return self._report_error("Failed to find home navigation while refreshing radio")
        home_nav.click()

        play_button = self._music.element_finder.wait_for_element_clickable("play_collection")
        if not play_button:
            return self._report_error("Failed to find collection play button after refresh")
        collection_topic = self._music.element_finder.wait_for_element("collection_topic")
        if not collection_topic:
            return self._report_error("Failed to locate collection radio topic after refresh")
        return play_button, collection_topic

    def _handle_sleep_healing(self, message_info) -> dict:
        from ushareiplay.helpers.playlist_info import (
            get_playlist_text_and_first_song,
        )

        error = self._navigate_home()
        if error:
            return error

        healing_room_name = "音乐疗愈"
        _, healing_tab, _ = self._music.gesture_handler.scroll_container_until_element(
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
        self._music.logger.info("Clicked 疗愈 tab after scrolling home tab strip")

        play_healing = self._music.element_finder.wait_for_element_clickable("play_healing")
        if not play_healing:
            return self._report_error("Failed to find healing play button")
        play_healing.click()
        playlist_info = self._music.get_playlist_info()
        playlist_text, first_song, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            self._music.logger.warning(
                f"Failed to read healing playlist after playback started: {error}"
            )
            playlist_text = healing_room_name
            first_song = None
        if not self._music.navigate_to_home():
            return self._report_error("Failed to navigate to home")
        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context(healing_room_name, first_song or None)
        if error:
            return error
        self._publish_playback(message_info, healing_room_name)
        return {"playlist": playlist_text}

    def _handle_radar(self, message_info) -> dict:
        from ushareiplay.helpers.playlist_info import (
            get_playlist_text_and_first_song,
        )

        error = self._navigate_home()
        if error:
            return error

        radar_nav = self._music.element_finder.try_find_element("radar_nav", log=False)
        if not radar_nav:
            return self._report_error("Cannot find radar_nav")
        radar_nav.click()
        self._music.logger.info("Clicked radar navigation button")

        radar_song = self._music.element_finder.wait_for_element_clickable("radar_song")
        radar_singer = self._music.element_finder.wait_for_element_clickable("radar_singer")
        if not radar_song or not radar_singer:
            return self._report_error("Failed to locate radar song or singer elements")

        song_text = radar_song.text
        singer_text = radar_singer.text
        playlist_info = self._music.get_playlist_info()
        playlist_text, _, error = get_playlist_text_and_first_song(playlist_info)
        if error:
            self._music.logger.warning(
                f"Failed to read radar playlist after playback started: {error}"
            )
            playlist_text = "O Radio"

        error = self._switch_back_to_soul()
        if error:
            return error
        error = self._set_room_context("O Radio", song_text)
        if error:
            return error
        self._publish_playback(message_info, "O Radio")
        return {"playlist": playlist_text, "song": song_text, "singer": singer_text, "album": ""}
