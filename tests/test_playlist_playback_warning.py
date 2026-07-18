from types import SimpleNamespace

from ushareiplay.commands.playlist import PlaylistCommand
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.title_manager import TitleManager
from ushareiplay.managers.topic_manager import TopicManager


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
    def __init__(self, text=""):
        self.text = text
        self.clicks = 0

    def click(self):
        self.clicks += 1


class _MusicHandler:
    def __init__(self):
        self.logger = _Logger()
        self.list_mode = None
        self.play_button = _Element("play")
        self.playlist_result = _Element("学习|英语")

    def query_music(self, query):
        return query == "study"

    def wait_for_any_element(self, keys):
        if keys == ["playlist_tab", "music_tabs"]:
            return "playlist_tab", _Element("playlist tab")
        if keys == ["playlist_result", "not_found"]:
            return "playlist_result", self.playlist_result
        if keys == ["play_all", "play_all_playlist", "play_all_compact"]:
            return "play_all", self.play_button
        raise AssertionError(f"unexpected keys: {keys}")

    def try_find_element(self, key):
        if key == "result_item":
            return None
        raise AssertionError(f"unexpected key: {key}")

    def get_playlist_info(self):
        return {"error": "No songs found in playlist"}

    @property
    def element_finder(self):
        return self


class _TitleManager:
    def __init__(self):
        self.titles = []

    def set_next_title(self, title):
        self.titles.append(title)


class _TopicManager:
    def __init__(self):
        self.topics = []

    def change_topic(self, topic):
        self.topics.append(topic)


class _InfoManager:
    def __init__(self):
        self.current_playlist_name = None


def test_playlist_info_error_warns_and_keeps_setting_room_context(monkeypatch):
    music_handler = _MusicHandler()
    title_manager = _TitleManager()
    topic_manager = _TopicManager()
    info_manager = _InfoManager()
    monkeypatch.setattr(TitleManager, "instance", lambda: title_manager)
    monkeypatch.setattr(TopicManager, "instance", lambda: topic_manager)
    monkeypatch.setattr(InfoManager, "instance", lambda: info_manager)

    command = PlaylistCommand(
        SimpleNamespace(
            music_handler=music_handler,
            soul_handler=SimpleNamespace(),
        )
    )

    result = command.play_playlist("study")

    assert "error" not in result
    assert result["playlist"] == "学习|英语"
    assert music_handler.play_button.clicks == 1
    assert music_handler.list_mode == "playlist"
    assert title_manager.titles == ["学习"]
    assert topic_manager.topics == ["英语"]
    assert info_manager.current_playlist_name == "学习|英语"
    assert any(
        level == "warning" and "No songs found in playlist" in message
        for level, message in music_handler.logger.messages
    )
