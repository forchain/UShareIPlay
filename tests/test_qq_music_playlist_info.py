from ushareiplay.handlers.qq_music_handler import QQMusicHandler


class _Logger:
    def __init__(self):
        self.errors = []

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        self.errors.append(message)


class _Element:
    def __init__(self, text="", location=None, size=None):
        self.text = text
        self.location = location or {"x": 0, "y": 0}
        self.size = size or {"width": 100, "height": 40}
        self.clicks = 0

    def click(self):
        self.clicks += 1

    def find_elements(self, by, value):
        return self.text


class _Driver:
    def __init__(self):
        self.swipes = []

    def swipe(self, start_x, start_y, end_x, end_y, duration):
        self.swipes.append((start_x, start_y, end_x, end_y, duration))


def _playlist_item(song, singer):
    return _Element([_Element(song), _Element(singer)])


def test_get_current_playing_treats_missing_playback_nodes_as_optional():
    handler = QQMusicHandler.__new__(QQMusicHandler)
    handler.logger = _Logger()
    handler.try_find_element = lambda key: None

    result = handler.get_current_playing()

    assert result is None
    assert handler.logger.errors == []


def _make_handler(monkeypatch, visible_items, current_song, updated_items=None, marker_exists=True):
    handler = QQMusicHandler.__new__(QQMusicHandler)
    handler.logger = _Logger()
    handler.play_mode_key = "unknown"
    handler.driver = _Driver()
    handler.playlist_entry = _Element("entry")
    handler.playlist_current_queries = 0
    handler.find_elements_calls = 0

    monkeypatch.setattr(handler, "switch_to_app", lambda: True)
    monkeypatch.setattr(handler, "press_back", lambda: None)
    monkeypatch.setattr(handler, "get_current_playing", lambda: {"song": current_song})
    monkeypatch.setattr(handler, "wait_for_element_clickable", lambda key: handler.playlist_entry)
    monkeypatch.setattr(handler, "try_find_any_element", lambda keys: (None, None))

    def try_find_element(key):
        if key == "playlist_entry":
            return handler.playlist_entry
        if key == "playlist_current":
            handler.playlist_current_queries += 1
            if not marker_exists:
                return None
            return _Element(location={"x": 10, "y": 300}, size={"width": 80, "height": 40})
        raise AssertionError(f"unexpected key: {key}")

    def find_elements(key):
        assert key == "playlist_item_container"
        handler.find_elements_calls += 1
        if handler.find_elements_calls == 1 or updated_items is None:
            return visible_items
        return updated_items

    monkeypatch.setattr(handler, "try_find_element", try_find_element)
    monkeypatch.setattr(handler, "find_elements", find_elements)
    return handler


def test_get_playlist_info_returns_initial_list_when_current_marker_is_absent(monkeypatch):
    handler = _make_handler(
        monkeypatch,
        visible_items=[
            _playlist_item("第一首", " - 歌手A"),
            _playlist_item("第二首", " - 歌手B"),
        ],
        current_song="不在首屏",
        marker_exists=False,
    )

    result = handler.get_playlist_info()

    assert result == {"playlist": "第一首 - 歌手A\n第二首 - 歌手B"}
    assert handler.playlist_current_queries == 1
    assert handler.driver.swipes == []
    assert handler.find_elements_calls == 1


def test_get_playlist_info_scrolls_when_marker_exists_but_current_title_is_not_visible(monkeypatch):
    handler = _make_handler(
        monkeypatch,
        visible_items=[
            _playlist_item("第一首", " - 歌手A"),
            _playlist_item("第二首", " - 歌手B"),
        ],
        current_song="不在首屏",
        updated_items=[
            _playlist_item("当前歌", " - 歌手C"),
            _playlist_item("第一首", " - 歌手A"),
        ],
    )

    result = handler.get_playlist_info()

    assert result == {"playlist": "当前歌 - 歌手C\n第一首 - 歌手A"}
    assert handler.playlist_current_queries == 1
    assert handler.driver.swipes == [(50, 320, 50, 0, 1000)]
    assert handler.find_elements_calls == 2


def test_get_playlist_info_scrolls_and_updates_playlist_when_current_title_visible(monkeypatch):
    handler = _make_handler(
        monkeypatch,
        visible_items=[
            _playlist_item("当前歌", " - 歌手A"),
            _playlist_item("第二首", " - 歌手B"),
        ],
        current_song="当前歌",
        updated_items=[
            _playlist_item("上一首", " - 歌手Z"),
            _playlist_item("当前歌", " - 歌手A"),
        ],
    )

    result = handler.get_playlist_info()

    assert result == {"playlist": "上一首 - 歌手Z\n当前歌 - 歌手A"}
    assert handler.playlist_current_queries == 1
    assert handler.driver.swipes == [(50, 320, 50, 0, 1000)]
    assert handler.find_elements_calls == 2
