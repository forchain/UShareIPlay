from types import SimpleNamespace

from selenium.common import StaleElementReferenceException

from ushareiplay.commands.play import PlayCommand
from ushareiplay.commands.radio import RadioCommand
from ushareiplay.handlers.qq_music_handler import QQMusicHandler
from ushareiplay.helpers.song_release import QQMusicSongReleaseLookup


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


class _Element:
    def __init__(self, text="", content_desc=None):
        self.text = text
        self.content_desc = content_desc
        self.clicks = 0

    def click(self):
        self.clicks += 1


class _StaleOnceElement:
    def __init__(self, text):
        self._text = text
        self._reads = 0

    @property
    def text(self):
        self._reads += 1
        if self._reads == 1:
            raise StaleElementReferenceException("stale topic")
        return self._text


class _MusicHandler:
    def __init__(self, playlists, topics=None):
        self.logger = _Logger()
        self.list_mode = "unknown"
        self.playlists = list(playlists)
        self.collection_title = _Element(content_desc="「每日推荐」音频按钮")
        self.topics = list(topics or ["默认话题"])
        self.stale_topics = set()
        self.play_buttons = []
        self.home_clicks = 0

    def switch_to_app(self):
        return True

    def navigate_to_home(self):
        return True

    def wait_for_any_element(self, keys):
        assert keys == ["pause_collection", "play_collection"]
        button = _Element("play")
        self.play_buttons.append(button)
        return "play_collection", button

    def wait_for_element_clickable(self, key):
        if key == "collection_title":
            return self.collection_title
        if key == "play_collection":
            button = _Element("play")
            self.play_buttons.append(button)
            return button
        if key == "home_nav":
            element = _Element("home")
            original_click = element.click

            def click():
                self.home_clicks += 1
                original_click()

            element.click = click
            return element
        raise AssertionError(f"unexpected clickable key: {key}")

    def wait_for_element(self, key):
        if key == "collection_topic":
            topic = self.topics.pop(0)
            if topic in self.stale_topics:
                self.stale_topics.remove(topic)
                self.topics.insert(0, topic)
                return _StaleOnceElement(topic)
            return _Element(topic)
        raise AssertionError(f"unexpected element key: {key}")

    def get_playlist_info(self):
        return {"playlist": self.playlists.pop(0)}


class _SoulHandler:
    def __init__(self):
        self.sent_messages = []

    def switch_to_app(self):
        return True

    def send_message(self, message):
        self.sent_messages.append(message)

    def try_get_attribute(self, element, attribute):
        assert attribute == "content-desc"
        return element.content_desc


class _TitleManager:
    def __init__(self):
        self.titles = []

    def set_next_title(self, title):
        self.titles.append(title)
        return {}


class _TopicManager:
    def __init__(self):
        self.topics = []

    def change_topic(self, topic):
        self.topics.append(topic)
        return {}


class _InfoManager:
    player_name = None
    current_playlist_name = None

    def is_user_online(self, _name):
        return False


def _make_command(monkeypatch, music_handler):
    title_manager = _TitleManager()
    topic_manager = _TopicManager()

    controller = SimpleNamespace(
        music_handler=music_handler,
        soul_handler=_SoulHandler(),
        config={
            "old_song_filter": {
                "enabled": True,
                "cutoff_date": "2000-01-01",
                "radio_max_refreshes": 3,
            }
        },
    )
    command = RadioCommand(controller)
    command._title_manager = title_manager
    command._topic_manager = topic_manager
    command._info_manager = _InfoManager()
    return command, title_manager, topic_manager


def test_default_radio_refreshes_until_first_song_is_not_old(monkeypatch):
    music_handler = _MusicHandler(
        ["新歌 - 歌手C\n第二首 - 歌手D"],
        topics=["老歌", "新歌"],
    )
    command, title_manager, topic_manager = _make_command(monkeypatch, music_handler)
    release_dates = {"老歌": "1999-12-31", "新歌": "2018-01-01"}
    monkeypatch.setattr(
        command.song_release_lookup,
        "get_release_date",
        lambda song: release_dates[song],
    )

    result = command._handle_collection(SimpleNamespace(nickname="Alice"))

    assert result == {"playlist": "新歌 - 歌手C\n第二首 - 歌手D"}
    assert len(music_handler.play_buttons) == 2
    assert [button.clicks for button in music_handler.play_buttons] == [0, 1]
    assert music_handler.home_clicks == 1
    assert title_manager.titles == ["新歌"]
    assert topic_manager.topics == ["每日推荐"]
    assert any("Radio recommendation candidate" in message for _, message in music_handler.logger.messages)
    assert any("refreshing recommendation" in message for _, message in music_handler.logger.messages)


def test_default_radio_accepts_song_when_release_date_unknown(monkeypatch):
    music_handler = _MusicHandler(["未知歌 - 歌手A"])
    command, _title_manager, _topic_manager = _make_command(monkeypatch, music_handler)
    monkeypatch.setattr(command.song_release_lookup, "get_release_date", lambda _song: None)

    result = command._handle_collection(SimpleNamespace(nickname="Alice"))

    assert result == {"playlist": "未知歌 - 歌手A"}
    assert len(music_handler.play_buttons) == 1
    assert music_handler.home_clicks == 0


def test_default_radio_refinds_stale_topic_after_refresh(monkeypatch):
    music_handler = _MusicHandler(
        ["新歌 - 歌手C"],
        topics=["老歌", "新歌"],
    )
    music_handler.stale_topics.add("新歌")
    command, title_manager, topic_manager = _make_command(monkeypatch, music_handler)
    release_dates = {"老歌": "1999-12-31", "新歌": "2018-01-01"}
    monkeypatch.setattr(
        command.song_release_lookup,
        "get_release_date",
        lambda song: release_dates[song],
    )

    result = command._handle_collection(SimpleNamespace(nickname="Alice"))

    assert result == {"playlist": "新歌 - 歌手C"}
    assert title_manager.titles == ["新歌"]
    assert topic_manager.topics == ["每日推荐"]
    assert any("stale" in message for _, message in music_handler.logger.messages)


def _make_handler_for_quality_check():
    handler = QQMusicHandler.__new__(QQMusicHandler)
    handler.logger = _Logger()
    handler.list_mode = "playlist"
    handler.no_skip = 0
    handler.song_release_lookup = QQMusicSongReleaseLookup()
    handler.config = {
        "old_song_filter": {
            "enabled": True,
            "cutoff_date": "2000-01-01",
        }
    }
    return handler


def test_quality_check_skips_old_song_for_any_playback_mode(monkeypatch):
    handler = _make_handler_for_quality_check()
    monkeypatch.setattr(handler.song_release_lookup, "get_release_date", lambda _song: "1999-01-01")

    should_skip = handler.should_skip_low_quality_song(
        {"song": "老歌", "singer": "歌手A", "album": "专辑A"}
    )

    assert should_skip is True


def test_quality_check_accepts_old_song_for_whitelisted_artist(monkeypatch):
    handler = _make_handler_for_quality_check()
    handler.config["old_song_filter"]["artist_whitelist"] = ["歌手A"]
    monkeypatch.setattr(handler.song_release_lookup, "get_release_date", lambda _song: "1999-01-01")
    song_info = {"song": "老歌", "singer": "歌手A/歌手B", "album": "专辑A"}

    should_skip = handler.should_skip_low_quality_song(song_info)

    assert should_skip is False
    assert song_info["release_date"] == "1999-01-01"


def test_quality_check_reads_artist_whitelist_from_controller_config(monkeypatch):
    handler = _make_handler_for_quality_check()
    handler.config = {}
    handler.controller = SimpleNamespace(
        config={
            "old_song_filter": {
                "enabled": True,
                "cutoff_date": "2000-01-01",
                "artist_whitelist": ["王菲", "911"],
            }
        }
    )
    monkeypatch.setattr(handler.song_release_lookup, "get_release_date", lambda _song: "1993-09-07")
    song_info = {"song": "如风", "singer": "王菲", "album": "十万个为什么？(日本版）"}

    should_skip = handler.should_skip_low_quality_song(song_info)

    assert should_skip is False
    assert song_info["release_date"] == "1993-09-07"


def test_quality_check_accepts_new_song_for_any_playback_mode(monkeypatch):
    handler = _make_handler_for_quality_check()
    monkeypatch.setattr(handler.song_release_lookup, "get_release_date", lambda _song: "2018-01-01")
    song_info = {"song": "新歌", "singer": "歌手A", "album": "专辑A"}

    should_skip = handler.should_skip_low_quality_song(song_info)

    assert should_skip is False
    assert song_info["release_date"] == "2018-01-01"


def test_ensure_release_date_populates_song_info_without_skip_decision(monkeypatch):
    handler = _make_handler_for_quality_check()
    monkeypatch.setattr(handler.song_release_lookup, "get_release_date", lambda _song: "1993-09-07")
    song_info = {"song": "如风", "singer": "王菲", "album": "十万个为什么？(日本版）"}

    handler.ensure_release_date(song_info)

    assert song_info["release_date"] == "1993-09-07"


class _PlayMusicHandler:
    def __init__(self):
        self.logger = _Logger()
        self.result_item = _Element("result")
        self.quality_checked = []
        self.playing_info = {
            "song": "似是故人来",
            "singer": "梅艳芳",
            "album": "戏剧人生",
        }

    def _prepare_music_playback(self, music_query):
        assert music_query == "似是故人来 梅艳芳"
        return self.playing_info

    def wait_for_element_clickable(self, key):
        assert key == "result_item"
        return self.result_item

    def ensure_favorited_in_playing_page(self, timeout=10):
        assert timeout == 10
        return True

    def handle_song_quality_check(self, song_info):
        self.quality_checked.append(song_info)
        return True


def test_play_command_checks_song_quality_immediately_after_playback_starts():
    music_handler = _PlayMusicHandler()
    controller = SimpleNamespace(
        music_handler=music_handler,
        soul_handler=SimpleNamespace(),
    )
    command = PlayCommand(controller)

    result = command.play_song("似是故人来 梅艳芳")

    assert result == music_handler.playing_info
    assert music_handler.result_item.clicks == 1
    assert music_handler.quality_checked == [music_handler.playing_info]
