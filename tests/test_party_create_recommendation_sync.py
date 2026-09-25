import pytest
from types import SimpleNamespace

from ushareiplay.state.room_state import RoomState
from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.managers.recommendation_manager import RecommendationManager
from ushareiplay.managers.room_info_window import RoomInfoWindow


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _Element:
    def __init__(self, text=""):
        self.text = text
        self.clicked = False

    def click(self):
        self.clicked = True


class _PartyFinder:
    """Party-side fake: no dialog is ever considered open."""

    def try_find_element(self, key, *args, **kwargs):
        return None

    def wait_for_element(self, key, *args, **kwargs):
        return None

    def wait_for_element_clickable(self, key, *args, **kwargs):
        return None

    def get_element_text(self, element):
        return getattr(element, "text", "")


class _RecFinder:
    def __init__(self, status_element=None):
        self.status_element = status_element

    def try_find_element(self, key, *args, **kwargs):
        if key == "party_recommendation_status":
            return self.status_element
        return None

    def wait_for_element(self, key, *args, **kwargs):
        return self.try_find_element(key)

    def wait_for_element_clickable(self, key, *args, **kwargs):
        return self.try_find_element(key)

    def get_element_text(self, element):
        return getattr(element, "text", "")


@pytest.fixture
def create_sync_setup(monkeypatch, tmp_path):
    """RoomState + RecommendationManager + RoomInfoWindow + PartyManager,
    mirroring the production composition (window module initialized)."""
    monkeypatch.chdir(tmp_path)  # isolate data/room_state.json persistence
    for cls in (RoomState, RecommendationManager, RoomInfoWindow, PartyManager):
        cls.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = _Logger()

    rec_manager = RecommendationManager.initialize()
    rec_manager._logger = _Logger()

    window = RoomInfoWindow.initialize()
    window._handler = SimpleNamespace(
        logger=_Logger(),
        element_finder=_PartyFinder(),  # no dialog marker is ever visible
        key_actions=SimpleNamespace(press_back=lambda: None),
        ui_actions=SimpleNamespace(switch_and_click=lambda key, **kwargs: {"success": True}),
    )
    window._logger = _Logger()

    calls = {"notice": 0, "seat": 0}

    async def set_default_notice():
        calls["notice"] += 1
        return {"success": True}

    async def find_owner_seat():
        calls["seat"] += 1
        return {"success": True}

    party_handler = SimpleNamespace(
        party_id="FM15321640",
        logger=_Logger(),
        element_finder=_PartyFinder(),
        key_actions=SimpleNamespace(press_back=lambda: None),
        config={},
        controller=SimpleNamespace(
            notice_manager=SimpleNamespace(set_default_notice=set_default_notice),
            seat_manager=SimpleNamespace(find_owner_seat=find_owner_seat),
        ),
    )
    party_manager = PartyManager.initialize()
    party_manager._handler = party_handler
    party_manager._logger = _Logger()

    rec_manager._handler = SimpleNamespace(
        element_finder=_RecFinder(),
        ui_actions=SimpleNamespace(
            switch_and_click=lambda key, **kwargs: {"success": True}
        ),
        key_actions=SimpleNamespace(press_back=lambda: None),
    )

    return party_manager, room_state, rec_manager, calls


async def test_after_party_created_refreshes_stale_closed_record_from_ui(create_sync_setup):
    """房间重启后实际为"所有人"（开放），但记录残留"关闭"：创建房间时须按真实 UI 更新。"""
    party_manager, room_state, rec_manager, calls = create_sync_setup

    room_state.recommendation_enabled = False  # stale record from before the restart
    rec_manager._handler.element_finder.status_element = _Element(text="所有人")

    await party_manager._after_party_created()

    assert room_state.recommendation_enabled is True
    # creation flow continues normally after the recommendation sync
    assert calls["notice"] == 1
    assert calls["seat"] == 1


async def test_after_party_created_overwrites_assumed_open_record_from_ui(create_sync_setup):
    """配置假设新房间默认开放，但真实 UI 为"关闭推荐分发"时，创建后记录应为关闭。"""
    party_manager, room_state, rec_manager, calls = create_sync_setup

    room_state.recommendation_enabled = True  # blind assumption from create_party_recommendation=true
    rec_manager._handler.element_finder.status_element = _Element(text="关闭推荐分发")

    await party_manager._after_party_created()

    assert room_state.recommendation_enabled is False
    assert calls["notice"] == 1


async def test_after_party_created_leaves_record_unsynced_when_ui_unreadable(create_sync_setup):
    """刷新失败时不得保留旧假设值：置为 None 让 info/回房时重新同步。"""
    party_manager, room_state, rec_manager, calls = create_sync_setup

    room_state.recommendation_enabled = False  # stale/assumed record
    rec_manager._handler.element_finder.status_element = None  # UI read fails

    await party_manager._after_party_created()

    assert room_state.recommendation_enabled is None
    # failure must not break the rest of the post-creation flow
    assert calls["notice"] == 1
    assert calls["seat"] == 1
