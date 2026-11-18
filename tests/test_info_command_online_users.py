import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from ushareiplay.adapters.inbound.chat.info import InfoCommand
from ushareiplay.modules.room import InfoManager, PresenceTracker, RoomAdmins, RoomStateService
from tests.seat_support import build_seat_observation
from ushareiplay.modules.seat.ledger import SeatSlot
from ushareiplay.modules.shared.message_info import MessageInfo
from ushareiplay.modules.playback.broadcaster import PlaybackBroadcaster
from ushareiplay.modules.playback.use_cases import PlaylistSession


@pytest.fixture(autouse=True)
def setup_info_env():
    global _room_admins, _info_manager, _presence
    _room_admins = RoomAdmins()

    playlist = PlaylistSession()
    broadcaster = PlaybackBroadcaster(playlist_session=playlist)
    _presence = PresenceTracker()
    _presence._logger = SimpleNamespace(info=lambda _msg: None, error=lambda _msg: None, critical=lambda _msg: None)
    _presence._online_users = set()
    room_state = RoomStateService()
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    _info_manager = InfoManager(
        room_state=room_state,
        presence=_presence,
        room_admins=_room_admins,
        playlist=playlist,
        playback_cache=broadcaster,
        logger=SimpleNamespace(info=lambda _msg: None),
    )
    yield


def make_dummy_controller():
    logger = MagicMock()
    soul_handler = SimpleNamespace(
        logger=logger,
        log_error=MagicMock(),
    )
    return SimpleNamespace(
        soul_handler=soul_handler,
        music_handler=SimpleNamespace(play_mode_key="unknown", play_mode_key_to_name=lambda _k: "未知"),
        logger=logger,
        info_manager=_info_manager,
        timer_manager=SimpleNamespace(status_line=lambda: "定时器: 已停止，共 0 个"),
        room_profile_manager=SimpleNamespace(recommendation_enabled=None),
    )


@pytest.mark.asyncio
async def test_info_online_users_empty():
    controller = make_dummy_controller()
    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="Alice")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "列表暂未更新"


@pytest.mark.asyncio
async def test_info_online_users_plain_users():
    _presence.update_online_users(["Alice", "Bob"])
    controller = make_dummy_controller()
    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="Alice")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "2人: Alice, Bob"


@pytest.mark.asyncio
async def test_info_online_users_admin_only():
    _presence.update_online_users(["AdminUser", "NormalUser"])
    _room_admins.add("AdminUser")

    controller = make_dummy_controller()
    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="NormalUser")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "2人: AdminUser(管理), NormalUser"


@pytest.mark.asyncio
async def test_info_online_users_seat_only():
    _presence.update_online_users(["SeatedUser", "NormalUser"])
    controller = make_dummy_controller()
    obs = build_seat_observation(controller.soul_handler)
    controller.seat_observation = obs
    obs.ledger.slots[3] = SeatSlot(seat_number=3, occupied=True, username="SeatedUser")

    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="NormalUser")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "2人: NormalUser, SeatedUser(3号)"


@pytest.mark.asyncio
async def test_info_online_users_admin_and_seat():
    _presence.update_online_users(["AdminOnSeat"])
    _room_admins.add("AdminOnSeat")

    controller = make_dummy_controller()
    obs = build_seat_observation(controller.soul_handler)
    controller.seat_observation = obs
    obs.ledger.slots[5] = SeatSlot(seat_number=5, occupied=True, username="AdminOnSeat")

    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="AdminOnSeat")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "1人: AdminOnSeat(管理, 5号)"


@pytest.mark.asyncio
async def test_info_online_users_all_combinations():
    users = ["AdminOffSeat", "AdminOnSeat", "NormalOffSeat", "NormalOnSeat"]
    _presence.update_online_users(users)

    _room_admins.add("AdminOffSeat")
    _room_admins.add("AdminOnSeat")

    controller = make_dummy_controller()
    obs = build_seat_observation(controller.soul_handler)
    controller.seat_observation = obs
    obs.ledger.slots[1] = SeatSlot(seat_number=1, occupied=True, username="AdminOnSeat")
    obs.ledger.slots[4] = SeatSlot(seat_number=4, occupied=True, username="NormalOnSeat")

    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="NormalOffSeat")

    res = await cmd.process(msg, [])
    expected = (
        "4人: AdminOffSeat(管理), AdminOnSeat(管理, 1号), "
        "NormalOffSeat, NormalOnSeat(4号)"
    )
    assert res["online_users"] == expected


@pytest.mark.asyncio
async def test_info_includes_timer_status():
    controller = make_dummy_controller()
    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="Alice")

    res = await cmd.process(msg, [])

    assert res["timer_status"] == "定时器: 已停止，共 0 个"


@pytest.mark.asyncio
async def test_info_online_users_without_optional_managers_initialized():
    _presence.update_online_users(["Alice", "Bob"])
    # 没有房管名单，也没有座位观测
    assert _room_admins.all() == set()

    controller = make_dummy_controller()
    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="Alice")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "2人: Alice, Bob"
