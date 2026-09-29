import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from ushareiplay.commands.info import InfoCommand
from ushareiplay.managers.admin_manager import AdminManager
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager, SeatSlot
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def setup_info_env():
    for cls in (
        InfoManager,
        PlaybackBroadcaster,
        PlaylistState,
        PresenceTracker,
        RoomState,
        AdminManager,
        SeatObservationManager,
    ):
        cls.reset_instance()

    PlaybackBroadcaster.initialize()
    PlaylistState.initialize()
    presence = PresenceTracker.initialize()
    presence._logger = SimpleNamespace(info=lambda _msg: None, error=lambda _msg: None, critical=lambda _msg: None)
    presence._online_users = set()
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    info_manager = InfoManager.initialize()
    info_manager._logger = SimpleNamespace(info=lambda _msg: None)
    info_manager._party_manager = SimpleNamespace(init_time=None)

    from unittest.mock import patch
    patcher = patch(
        "ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance",
        return_value=SimpleNamespace(play_mode_key="unknown", play_mode_key_to_name=lambda _k: "未知"),
    )
    patcher.start()

    yield

    patcher.stop()

    for cls in (
        InfoManager,
        PlaybackBroadcaster,
        PlaylistState,
        PresenceTracker,
        RoomState,
        AdminManager,
        SeatObservationManager,
    ):
        cls.reset_instance()


def make_dummy_controller():
    logger = MagicMock()
    soul_handler = SimpleNamespace(
        logger=logger,
        log_error=MagicMock(),
    )
    return SimpleNamespace(
        soul_handler=soul_handler,
        music_handler=None,
        logger=logger,
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
    PresenceTracker.instance().update_online_users(["Alice", "Bob"])
    controller = make_dummy_controller()
    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="Alice")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "2人: Alice, Bob"


@pytest.mark.asyncio
async def test_info_online_users_admin_only():
    PresenceTracker.instance().update_online_users(["AdminUser", "NormalUser"])
    admin_mgr = AdminManager.initialize()
    admin_mgr.add_room_admin("AdminUser")

    controller = make_dummy_controller()
    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="NormalUser")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "2人: AdminUser(管理), NormalUser"


@pytest.mark.asyncio
async def test_info_online_users_seat_only():
    PresenceTracker.instance().update_online_users(["SeatedUser", "NormalUser"])
    controller = make_dummy_controller()
    obs = SeatObservationManager.initialize(controller.soul_handler)
    obs.seats[3] = SeatSlot(seat_number=3, occupied=True, username="SeatedUser")

    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="NormalUser")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "2人: NormalUser, SeatedUser(3号)"


@pytest.mark.asyncio
async def test_info_online_users_admin_and_seat():
    PresenceTracker.instance().update_online_users(["AdminOnSeat"])
    admin_mgr = AdminManager.initialize()
    admin_mgr.add_room_admin("AdminOnSeat")

    controller = make_dummy_controller()
    obs = SeatObservationManager.initialize(controller.soul_handler)
    obs.seats[5] = SeatSlot(seat_number=5, occupied=True, username="AdminOnSeat")

    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="AdminOnSeat")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "1人: AdminOnSeat(管理, 5号)"


@pytest.mark.asyncio
async def test_info_online_users_all_combinations():
    users = ["AdminOffSeat", "AdminOnSeat", "NormalOffSeat", "NormalOnSeat"]
    PresenceTracker.instance().update_online_users(users)

    admin_mgr = AdminManager.initialize()
    admin_mgr.add_room_admin("AdminOffSeat")
    admin_mgr.add_room_admin("AdminOnSeat")

    controller = make_dummy_controller()
    obs = SeatObservationManager.initialize(controller.soul_handler)
    obs.seats[1] = SeatSlot(seat_number=1, occupied=True, username="AdminOnSeat")
    obs.seats[4] = SeatSlot(seat_number=4, occupied=True, username="NormalOnSeat")

    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="NormalOffSeat")

    res = await cmd.process(msg, [])
    expected = (
        "4人: AdminOffSeat(管理), AdminOnSeat(管理, 1号), "
        "NormalOffSeat, NormalOnSeat(4号)"
    )
    assert res["online_users"] == expected


@pytest.mark.asyncio
async def test_info_online_users_without_optional_managers_initialized():
    PresenceTracker.instance().update_online_users(["Alice", "Bob"])
    # AdminManager and SeatObservationManager are NOT initialized
    assert not AdminManager.is_initialized()
    assert not SeatObservationManager.is_initialized()

    controller = make_dummy_controller()
    cmd = InfoCommand(controller)
    msg = MessageInfo(content=":info", nickname="Alice")

    res = await cmd.process(msg, [])
    assert res["online_users"] == "2人: Alice, Bob"
