from types import SimpleNamespace
import pytest

from ushareiplay.commands.info import InfoCommand
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.recommendation_manager import RecommendationManager


class MockElementFinder:
    def __init__(self, elements=None):
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
def info_cmd_setup():
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
    info_manager._online_users = set()
    info_manager._party_manager = SimpleNamespace(init_time=None)
    rec_manager = RecommendationManager.initialize()
    rec_manager._logger = SimpleNamespace(info=lambda _msg: None, error=lambda _msg: None, warning=lambda _msg: None)

    title_elem = MockElement(text="所有人")
    opt_open = MockElement(text="所有人")

    soul_handler = SimpleNamespace(
        element_finder=MockElementFinder(
            elements={
                "chat_room_title": MockElement(),
                "party_recommendation_status": title_elem,
                "party_recommendation_open": opt_open,
            }
        ),
        ui_actions=SimpleNamespace(switch_and_click=lambda key, **kwargs: {'success': True}),
        key_actions=SimpleNamespace(switch_to_app=lambda: True, press_back=lambda: None),
        logger=SimpleNamespace(info=lambda _msg: None, error=lambda _msg: None, warning=lambda _msg: None),
        config={"create_party_recommendation": True},
    )
    rec_manager._handler = soul_handler

    music_handler = SimpleNamespace(play_mode_key="unknown", play_mode_key_to_name=lambda _k: "未知")
    controller = SimpleNamespace(soul_handler=soul_handler, music_handler=music_handler)
    cmd = InfoCommand(controller)
    return cmd, room_state, info_manager


@pytest.mark.asyncio
async def test_info_command_fetches_recommendation_status_when_unknown(monkeypatch, info_cmd_setup):
    cmd, room_state, info_manager = info_cmd_setup
    monkeypatch.setattr(
        "ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance",
        lambda: SimpleNamespace(play_mode_key="unknown", play_mode_key_to_name=lambda _k: "未知"),
    )

    room_state.recommendation_enabled = None
    result = await cmd.do_process(SimpleNamespace(nickname="Console"), [])

    assert result["party_recommendation"] == "开放"
    assert room_state.recommendation_enabled is True
