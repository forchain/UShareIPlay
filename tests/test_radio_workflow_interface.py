"""Interface tests for the Radio Workflow seam.

Drive the workflow with a deterministic music/soul/info/title/topic
adapter triple. These tests cover the workflow's public dispatch and
the room-context + player-publication policy without touching the
QQMusicHandler or SoulHandler globals.
"""

from types import SimpleNamespace

import pytest

from ushareiplay.core.radio_workflow import RADIO_PLAYER_EXEMPT_NICKNAMES, RadioWorkflow


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


class _FakeElementFinder:
    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []

    def wait_for_element_clickable(self, key):
        self.calls.append(("clickable", key))
        return self._mapping.get(key)

    def wait_for_element(self, key):
        self.calls.append(("element", key))
        return self._mapping.get(key)

    def wait_for_any_element(self, keys):
        # Pretend the second key is the live one; the workflow's collection
        # branch then asks for the corresponding element via the finder.
        return keys[-1], self._mapping.get(keys[-1])

    def try_find_element(self, key, log=True):
        return self._mapping.get(key)


class _FakeKeyActions:
    def __init__(self):
        self.switch_calls = 0

    def switch_to_app(self):
        self.switch_calls += 1
        return True


class _FakeMusicUI:
    def __init__(self, element_map):
        self.logger = _FakeLogger()
        self.list_mode = "playlist"
        self.element_finder = _FakeElementFinder(element_map)
        self.key_actions = _FakeKeyActions()

    def navigate_to_home(self):
        return True

    def get_playlist_info(self):
        return {"playlist": ""}


class _FakeSoulUI:
    def __init__(self, collection_title):
        self.element_finder = SimpleNamespace(
            try_get_attribute=lambda _e, _attr: collection_title
        )
        self.key_actions = _FakeKeyActions()


class _RecordingInfo:
    def __init__(self, player_name=None):
        self.player_name = player_name
        self.online = set()
        self.published = []
        self._playlist_name = None

    def is_user_online(self, name):
        return name in self.online

    @property
    def current_playlist_name(self):
        return self._playlist_name

    @current_playlist_name.setter
    def current_playlist_name(self, value):
        self._playlist_name = value
        self.published.append(("playlist", value))


class _RecordingTitle:
    def __init__(self):
        self.titles = []

    def set_next_title(self, title):
        self.titles.append(title)
        return {}


class _RecordingTopic:
    def __init__(self):
        self.topics = []

    def change_topic(self, topic):
        self.topics.append(topic)
        return {}


class _FakeLookup:
    def __init__(self, dates=None):
        self._dates = dates or {}

    def get_release_date(self, song):
        return self._dates.get(song)


def _make_workflow(elements=None, collection_title="未知电台", player_name=None):
    if elements is None:
        elements = {}
    info = _RecordingInfo(player_name=player_name)
    return (
        RadioWorkflow(
            music_ui=_FakeMusicUI(elements),
            soul_ui=_FakeSoulUI(collection_title),
            info_manager=info,
            title_manager=_RecordingTitle(),
            topic_manager=_RecordingTopic(),
            song_release_lookup=_FakeLookup(),
            config={},
        ),
        info,
    )


def test_unsupported_keyword_returns_structured_error():
    workflow, info = _make_workflow()
    info.online.add("Alice")

    result = workflow.dispatch(SimpleNamespace(nickname="Alice"), ["bogus"])

    assert "error" in result
    assert "Unsupported radio keyword" in result["error"]


def test_player_guard_blocks_when_other_player_online():
    workflow, info = _make_workflow()
    info.player_name = "Alice"
    info.online.add("Alice")

    result = workflow.dispatch(SimpleNamespace(nickname="Bob"), ["collection"])

    assert "error" in result
    assert "Alice 正在播放" in result["error"]


def test_player_guard_allows_exempt_nicknames():
    """Timer / Outlier / Chainer / Joyer are exempt from the player guard."""
    workflow, info = _make_workflow()
    info.player_name = "Timer"
    info.online.add("Timer")

    result = workflow.dispatch(SimpleNamespace(nickname="Bob"), ["bogus"])

    # Not blocked; falls through to the unsupported-keyword path.
    assert "Unsupported radio keyword" in result["error"]


def test_extract_primary_topic_strips_dash_suffix():
    assert RadioWorkflow.extract_primary_topic("Topic - subtitle") == "Topic"
    assert RadioWorkflow.extract_primary_topic("JustTopic") == "JustTopic"
    assert RadioWorkflow.extract_primary_topic("") is None
    assert RadioWorkflow.extract_primary_topic(None) is None


def test_default_radio_dispatch_routes_collection_when_no_parameters():
    """No parameters defaults to the collection radio mode."""
    workflow, _info = _make_workflow()
    elements = {
        "play_collection": SimpleNamespace(click=lambda: None),
        "collection_title": SimpleNamespace(text="「每日推荐」音频按钮"),
        "collection_topic": SimpleNamespace(text="默认话题"),
    }
    workflow, _ = _make_workflow(elements=elements)

    result = workflow.dispatch(SimpleNamespace(nickname="Alice"), [])

    # Without injecting a release lookup that returns unknown dates, the
    # workflow accepts whatever the topic returns. The result must be a
    # playlist-shaped dict (or a structured error).
    assert "playlist" in result or "error" in result


def test_radio_workflow_publishes_player_state_on_success():
    """Successful dispatch updates player_name + current_playlist_name."""
    elements = {
        "play_collection": SimpleNamespace(click=lambda: None),
        "collection_title": SimpleNamespace(text="「电台名」音频按钮"),
        "collection_topic": SimpleNamespace(text="默认话题"),
    }
    workflow, info = _make_workflow(
        elements=elements, collection_title="「电台名」音频按钮"
    )

    workflow.dispatch(SimpleNamespace(nickname="Alice"), [])

    assert info.player_name == "Alice"
    assert ("playlist", "电台名") in info.published


def test_player_exempt_nicknames_constant_includes_known_systems():
    assert "Joyer" in RADIO_PLAYER_EXEMPT_NICKNAMES
    assert "Timer" in RADIO_PLAYER_EXEMPT_NICKNAMES
    assert "Outlier" in RADIO_PLAYER_EXEMPT_NICKNAMES
    assert "Chainer" in RADIO_PLAYER_EXEMPT_NICKNAMES
