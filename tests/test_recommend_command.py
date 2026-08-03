from types import SimpleNamespace
import pytest

from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.recommendation_manager import RecommendationManager
from ushareiplay.commands.recommend import RecommendCommand


class MockElementFinder:
    def __init__(self, elements=None):
        self.elements = elements or {}

    def try_find_element(self, key, log=True):
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
def recommend_cmd_setup():
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
    rec_manager._logger = SimpleNamespace(info=lambda _msg: None)

    title_elem = MockElement(text="所有人")
    opt_close = MockElement(text="关闭推荐分发")
    pressed_back = False

    def press_back():
        nonlocal pressed_back
        pressed_back = True

    soul_handler = SimpleNamespace(
        element_finder=MockElementFinder(
            elements={
                "party_recommendation_status": title_elem,
                "party_recommendation_close": opt_close,
            }
        ),
        ui_actions=SimpleNamespace(switch_and_click=lambda key, **kwargs: {'success': True}),
        key_actions=SimpleNamespace(switch_to_app=lambda: True, press_back=press_back),
        logger=SimpleNamespace(info=lambda _msg: None, error=lambda _msg: None),
    )
    rec_manager._handler = soul_handler
    cmd = RecommendCommand(
        SimpleNamespace(soul_handler=soul_handler, music_handler=SimpleNamespace())
    )
    return cmd, room_state, title_elem, opt_close


@pytest.mark.asyncio
async def test_recommend_command_toggle_from_open_to_closed(recommend_cmd_setup):
    cmd, room_state, title_elem, opt_close = recommend_cmd_setup
    room_state.recommendation_enabled = True

    result = await cmd.do_process(SimpleNamespace(nickname="Console"), [])

    assert "error" not in result
    assert result.get("status") == "关闭"
    assert room_state.recommendation_enabled is False
    assert opt_close.clicked is True


@pytest.mark.asyncio
async def test_recommend_command_explicit_on(recommend_cmd_setup):
    cmd, room_state, title_elem, opt_close = recommend_cmd_setup
    room_state.recommendation_enabled = False
    title_elem.text = "关闭推荐分发"

    opt_open = MockElement(text="所有人")
    cmd.handler.element_finder.elements["party_recommendation_open"] = opt_open

    result = await cmd.do_process(SimpleNamespace(nickname="Console"), ["on"])

    assert "error" not in result
    assert result.get("status") == "开放"
    assert room_state.recommendation_enabled is True
    assert opt_open.clicked is True
