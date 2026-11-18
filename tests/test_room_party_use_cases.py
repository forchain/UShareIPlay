from datetime import datetime, timedelta

import pytest

from tests.fakes.in_memory_luck_pack_driver import InMemoryLuckPackDriver
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver
from tests.fakes.in_memory_party_driver import InMemoryPartyDriver
from tests.fakes.in_memory_room_messenger import InMemoryRoomMessenger
from tests.fakes.in_memory_user_repository import InMemoryUserRepository
from ushareiplay.modules.room.domain import PartyLifecycleState, RoomAdmins
from ushareiplay.modules.room.ports import GIFT_ACTION_USE, PlaylistQueryPort, PlaybackCacheQueryPort
from ushareiplay.modules.room.use_cases import (
    InfoManager,
    LuckPackService,
    OnlineDrawer,
    PartyService,
    PresenceTracker,
    RoomStateService,
    UserProfileActions,
)
from ushareiplay.modules.shared.config import ConfigSectionView


class _FakePlaylist(PlaylistQueryPort):
    def __init__(self):
        self._player_name = "Alice"
        self._playlist_name = "Chill Mix"
        self._pending = 2
        self._contributors = {"Bob"}

    @property
    def player_name(self) -> str:
        return self._player_name

    @property
    def current_playlist_name(self) -> str:
        return self._playlist_name

    @property
    def pending_next_count(self) -> int:
        return self._pending

    @property
    def next_queue_contributors(self) -> set[str]:
        return set(self._contributors)

    def get_playlist_info(self):
        return {"type": "playlist", "name": self._playlist_name}


class _FakePlaybackCache(PlaybackCacheQueryPort):
    def __init__(self, cache):
        self._cache = cache

    def get_playback_info_cache(self):
        return self._cache

    def ensure_cached_release_date(self):
        return self._cache


def test_party_service_end_party_resets_state_and_notifies_memory():
    driver = InMemoryPartyDriver(party_id="FM100")
    room_state = RoomStateService(default_party_id="FM100")
    room_state.expected_party_id = "FM200"
    room_state.room_id = "FM200"
    messenger = InMemoryRoomMessenger()
    scheduled = []

    service = PartyService(
        driver=driver,
        room_state=room_state,
        messenger=messenger,
        on_memory_consolidate=lambda: scheduled.append(True),
    )
    result = service.end_party()

    assert result == {"success": "Party ended"}
    assert messenger.messages == ["Ending party"]
    assert room_state.expected_party_id is None
    assert room_state.room_id is None
    assert driver.get_party_id() is None
    assert scheduled == [True]


@pytest.mark.asyncio
async def test_party_service_invite_user_checks_online_then_switches():
    driver = InMemoryPartyDriver(party_id="FM100", online_parties={"FM999"})
    room_state = RoomStateService(default_party_id="FM100")
    service = PartyService(driver=driver, room_state=room_state)

    result = await service.invite_user("Alice", "FM999")
    assert result == {"party_id": "FM999", "user": "Alice"}
    assert room_state.expected_party_id == "FM999"
    assert room_state.room_id == "FM999"
    assert driver.get_party_id() == "FM999"


@pytest.mark.asyncio
async def test_party_service_invite_user_returns_error_when_offline():
    driver = InMemoryPartyDriver(party_id="FM100", online_parties=set())
    room_state = RoomStateService(default_party_id="FM100")
    service = PartyService(driver=driver, room_state=room_state)

    result = await service.invite_user("Alice", "FM999")
    assert result == {"error": "Party FM999 is closed or not found", "party_id": "FM999"}
    assert ("end_party_ui",) not in driver.calls


def test_party_service_auto_restart_triggers_once_per_day():
    driver = InMemoryPartyDriver(party_id="FM100")
    room_state = RoomStateService(default_party_id="FM100")
    room_state.user_count = 1
    lifecycle = PartyLifecycleState(trigger_minutes=10)
    lifecycle.initialize(now=datetime.now() - timedelta(minutes=20), trigger_minutes=10)

    service = PartyService(driver=driver, room_state=room_state, lifecycle=lifecycle)
    service.update()
    assert driver.calls.count(("end_party_ui",)) == 1

    # Second call same day must not repeat
    service.update()
    assert driver.calls.count(("end_party_ui",)) == 1


@pytest.mark.asyncio
async def test_info_manager_is_read_only_facade_over_ports():
    room_state = RoomStateService(default_party_id="FM100")
    room_state.room_id = "FM100"
    room_state.user_count = 7
    room_state.focus_count = 3
    room_state.recommendation_enabled = True

    presence = PresenceTracker()
    presence.update_online_users(["Alice", "Bob"])

    admins = RoomAdmins()
    admins.add("Alice")

    lifecycle = PartyLifecycleState()
    lifecycle.initialize(now=datetime(2026, 11, 18, 12, 0, 0))

    users = InMemoryUserRepository()
    await users.get_or_create("Alice")

    info = InfoManager(
        room_state=room_state,
        presence=presence,
        room_admins=admins,
        playlist=_FakePlaylist(),
        playback_cache=_FakePlaybackCache({"song": "晴天", "singer": "周杰伦"}),
        party_lifecycle=lifecycle,
        users=users,
    )

    assert info.room_id == "FM100"
    assert info.user_count == 7
    assert info.focus_count == 3
    assert info.recommendation_enabled is True
    assert info.is_user_online("Alice") is True
    assert info.get_online_users() == {"Alice", "Bob"}
    assert info.get_room_admins() == {"Alice"}
    assert info.player_name == "Alice"
    assert info.current_playlist_name == "Chill Mix"
    assert info.pending_next_count == 2
    assert info.next_queue_contributors == {"Bob"}
    assert info.get_playlist_info() == {"type": "playlist", "name": "Chill Mix"}
    assert info.get_playback_info_cache() == {"song": "晴天", "singer": "周杰伦"}
    assert info.get_party_duration_info() is not None
    assert await info.resolve_visible_username("Alice") == "Alice"

    # InfoManager must not expose write methods
    for write_attr in ("update_online_users", "set_user_count", "clear", "refresh_online_users"):
        assert not hasattr(info, write_attr)
    with pytest.raises(AttributeError):
        info.user_count = 99


@pytest.mark.asyncio
async def test_user_profile_actions_send_gift_and_private_message():
    driver = InMemoryOnlineDrawerDriver(
        members=["Alice"],
        gift_action_key=GIFT_ACTION_USE,
        gift_name="初级福袋x2",
    )
    drawer = OnlineDrawer(drawer=driver)
    actions = UserProfileActions(drawer=drawer)

    res = await actions.send_gift("Alice")
    assert res == {"success": "初级福袋 送你啦"}
    assert driver.drawer_open is False

    sent = await actions.send_private_message_to_user("Alice", "hello")
    assert sent is True


def test_luck_pack_service_list_open_and_redeem():
    driver = InMemoryLuckPackDriver(
        packs=[(3, "高级福袋"), (1, "初级福袋")],
        heat_sequence=[500, 200, 0],
        tiers=[100, 300],
    )
    room_state = RoomStateService(default_party_id="FM100")
    service = LuckPackService(driver=driver, room_state=room_state)

    listed = service.list_packs()
    assert listed == {"message": "福袋列表（共2个）：高级福袋（3级）、初级福袋（1级）"}
    assert driver.drawer_closed_count == 1

    opened = service.open_pack(["1", "3"])
    assert opened == {"message": "已开启1级福袋"}
    assert driver.use_pack_clicks == 1

    redeemed = service.redeem_heat()
    assert redeemed == {"message": "成功兑换 2 个福袋，剩余热力值: 0"}
    assert driver.redeemed_costs == [300, 100]
    assert driver.exchange_closed_count == 1

    # Auto open when user_count > 5
    room_state.user_count = 6
    service.update()
    assert driver.auto_open_calls == [(6, True)]
