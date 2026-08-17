from types import SimpleNamespace
import pytest

from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.recommendation_manager import RecommendationManager


class MockElementFinder:
    def __init__(self, texts=None, elements=None):
        self.texts = texts or {}
        self.elements = elements or {}

    def try_find_element(self, key, log=True):
        return self.elements.get(key)

    def wait_for_element(self, key):
        return self.elements.get(key)

    def wait_for_element_clickable(self, key):
        return self.elements.get(key)

    def get_element_text(self, element):
        return getattr(element, "text", "")


class MockElement:
    def __init__(self, text=""):
        self.text = text
        self.clicked = False

    def click(self):
        self.clicked = True


@pytest.fixture
def recommendation_setup():
    for cls in (
        InfoManager,
        PlaybackBroadcaster,
        PlaylistState,
        PresenceTracker,
        RoomState,
        RecommendationManager,
    ):
        cls.reset_instance()
    PlaybackBroadcaster.initialize()
    PlaylistState.initialize()
    PresenceTracker.initialize()
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    info_manager = InfoManager.initialize()
    info_manager._logger = SimpleNamespace(info=lambda _msg: None)
    rec_manager = RecommendationManager.initialize()
    rec_manager._logger = SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None)
    return rec_manager, room_state


def test_inspect_current_ui_status(recommendation_setup):
    rec_manager, room_state = recommendation_setup
    title_elem = MockElement(text="所有人")
    handler = SimpleNamespace(
        element_finder=MockElementFinder(elements={"party_recommendation_status": title_elem})
    )
    rec_manager._handler = handler

    status = rec_manager.inspect_current_ui_status()
    assert status is True

    title_elem.text = "关闭推荐分发"
    status = rec_manager.inspect_current_ui_status()
    assert status is False

    title_elem.text = "其他未知状态"
    status = rec_manager.inspect_current_ui_status()
    assert status is None


def test_sync_ui_status_if_dialog_open_updates_room_state(recommendation_setup):
    rec_manager, room_state = recommendation_setup
    title_elem = MockElement(text="所有人")
    handler = SimpleNamespace(
        element_finder=MockElementFinder(elements={"party_recommendation_status": title_elem})
    )
    rec_manager._handler = handler

    room_state.recommendation_enabled = False
    status = rec_manager.sync_ui_status_if_dialog_open()

    assert status is True
    assert room_state.recommendation_enabled is True


def test_ensure_synced_on_return_skips_when_already_saved(recommendation_setup):
    rec_manager, room_state = recommendation_setup
    room_state.recommendation_enabled = True

    result = rec_manager.ensure_synced_on_return()
    assert result.get("skipped") is True
    assert result.get("reason") == "already_saved"


def test_ensure_synced_on_return_reads_ui_without_clicking_options(recommendation_setup):
    rec_manager, room_state = recommendation_setup
    room_state.recommendation_enabled = None

    title_elem = MockElement(text="所有人")
    chat_title = MockElement()
    opt_open = MockElement(text="所有人")
    back_count = 0

    def press_back():
        nonlocal back_count
        back_count += 1

    handler = SimpleNamespace(
        element_finder=MockElementFinder(
            elements={
                "chat_room_title": chat_title,
                "party_recommendation_status": title_elem,
                "party_recommendation_open": opt_open,
            }
        ),
        ui_actions=SimpleNamespace(switch_and_click=lambda key, **kwargs: {'success': True}),
        key_actions=SimpleNamespace(press_back=press_back),
        config={"create_party_recommendation": True},
    )
    rec_manager._handler = handler

    result = rec_manager.ensure_synced_on_return()

    assert result.get("success") is True
    assert room_state.recommendation_enabled is True
    assert title_elem.clicked is False
    assert opt_open.clicked is False
    assert back_count == 1


def test_close_title_dialog_presses_back_twice_if_window_still_open(recommendation_setup):
    rec_manager, room_state = recommendation_setup
    back_count = 0
    finder = MockElementFinder()

    def press_back():
        nonlocal back_count
        back_count += 1
        if back_count == 1:
            finder.elements["party_recommendation_status"] = MockElement(text="关闭推荐分发")
        else:
            finder.elements.pop("party_recommendation_status", None)

    handler = SimpleNamespace(
        element_finder=finder,
        key_actions=SimpleNamespace(press_back=press_back),
        logger=SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None),
    )
    rec_manager._handler = handler

    rec_manager.close_title_dialog()
    assert back_count == 2
