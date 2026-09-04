import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from ushareiplay.commands.radio import RadioCommand
from ushareiplay.commands.playlist import PlaylistCommand
from ushareiplay.commands.album import AlbumCommand
from ushareiplay.commands.singer import SingerCommand
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.state.online_list_scraper import OnlineListScraper
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.state.playlist_state import PlaylistState
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState
from ushareiplay.models.user import User
from ushareiplay.dal.user_dao import UserDAO
from tortoise import Tortoise
import pytest_asyncio


@pytest_asyncio.fixture
async def user_db():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["ushareiplay.models.user"]},
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


@pytest.fixture
def clean_info_manager():
    for cls in (
        InfoManager,
        RoomState,
        PresenceTracker,
        PlaylistState,
        PlaybackBroadcaster,
        OnlineListScraper,
    ):
        cls.reset_instance()
    RoomState.initialize()
    PresenceTracker.initialize()
    PlaylistState.initialize()
    PlaybackBroadcaster.initialize()
    OnlineListScraper.initialize()
    manager = InfoManager.initialize()
    manager._logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    return manager


@pytest.mark.asyncio
async def test_radio_empty_params_blocked_when_user_is_playing(clean_info_manager):
    """
    当正常用户正在播放歌单且在线时，定时器或其他人触发无参数的 /radio 命令，
    必须被歌单守护拦截，不得顶掉当前用户的歌单。
    """
    info_manager = clean_info_manager
    info_manager.player_name = "不约儿童🐏🐏"
    info_manager.update_online_users(["不约儿童🐏🐏", "Joyer", "Chainer"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    mock_controller.config = {
        "soul": {"room_owner": "Joyer", "system_users": ["Timer", "Console", "Agent"]}
    }

    command = RadioCommand(mock_controller)
    msg = MessageInfo(content="/radio", nickname="Timer")

    res = await command.do_process(msg, [])
    assert isinstance(res, dict)
    assert res.get("error") == "不约儿童🐏🐏 正在播放歌单，请等待"
    mock_controller.music_handler.navigate_to_home.assert_not_called()


@pytest.mark.asyncio
async def test_radio_empty_params_allowed_when_timer_or_admin_is_playing(clean_info_manager):
    """
    当当前播放者是 Timer 或系统管理员（如 Joyer）时，整点定时器触发 /radio 应该被允许执行。
    """
    info_manager = clean_info_manager
    info_manager.player_name = "Timer"
    info_manager.update_online_users(["Joyer", "Chainer"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    mock_controller.config = {
        "soul": {"room_owner": "Joyer", "system_users": ["Timer", "Console", "Agent"]}
    }

    command = RadioCommand(mock_controller)
    command._handle_collection = MagicMock(return_value={"playlist": "测试电台"})

    msg = MessageInfo(content="/radio", nickname="Timer")
    res = await command.do_process(msg, [])

    assert res == {"playlist": "测试电台"}
    command._handle_collection.assert_called_once_with(msg)


@pytest.mark.asyncio
async def test_playlist_guardian_protects_with_avatar_online(user_db, clean_info_manager):
    """
    测试守护者本人昵称不在房间，但其分身仍在房间时，歌单仍受到守护。
    """
    canonical = await User.create(username="不约儿童🐏🐏", level=0)
    await User.create(username="儿童不易~🐏🐏", level=0, canonical_user_id=canonical.id)

    info_manager = clean_info_manager
    info_manager.player_name = "不约儿童🐏🐏"
    # 房间在线列表中只有分身 "儿童不易~🐏🐏"
    info_manager.update_online_users(["儿童不易~🐏🐏", "Joyer"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    mock_controller.config = {
        "soul": {"room_owner": "Joyer", "system_users": ["Timer", "Console", "Agent"]}
    }

    command = RadioCommand(mock_controller)
    msg = MessageInfo(content="/radio", nickname="Timer")

    res = await command.do_process(msg, [])
    assert isinstance(res, dict)
    assert res.get("error") == "不约儿童🐏🐏 正在播放歌单，请等待"


@pytest.mark.asyncio
async def test_playlist_guardian_allows_same_user_avatar_to_change_playlist(user_db, clean_info_manager):
    """
    测试守护者用分身切歌时，不应被自己守护的歌单拦截。
    """
    canonical = await User.create(username="不约儿童🐏🐏", level=0)
    await User.create(username="儿童不易~🐏🐏", level=0, canonical_user_id=canonical.id)

    info_manager = clean_info_manager
    info_manager.player_name = "不约儿童🐏🐏"
    info_manager.update_online_users(["儿童不易~🐏🐏", "Joyer"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    mock_controller.config = {
        "soul": {"room_owner": "Joyer", "system_users": ["Timer", "Console", "Agent"]}
    }

    command = RadioCommand(mock_controller)
    command._handle_collection = MagicMock(return_value={"playlist": "新电台"})

    # 分身发出的切歌命令
    msg = MessageInfo(content="/radio", nickname="儿童不易~🐏🐏")
    res = await command.do_process(msg, [])
    assert res == {"playlist": "新电台"}
    command._handle_collection.assert_called_once_with(msg)


@pytest.mark.asyncio
async def test_playlist_guardian_released_when_all_avatars_leave(user_db, clean_info_manager):
    """
    当守护者及其所有分身均离开房间后，守护解除，定时器可以切歌。
    """
    canonical = await User.create(username="不约儿童🐏🐏", level=0)
    await User.create(username="儿童不易~🐏🐏", level=0, canonical_user_id=canonical.id)

    info_manager = clean_info_manager
    info_manager.player_name = "不约儿童🐏🐏"
    # 主账号和分身均不在在线列表中
    info_manager.update_online_users(["其他房客", "Joyer"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    mock_controller.config = {
        "soul": {"room_owner": "Joyer", "system_users": ["Timer", "Console", "Agent"]}
    }

    command = RadioCommand(mock_controller)
    command._handle_collection = MagicMock(return_value={"playlist": "新电台"})

    msg = MessageInfo(content="/radio", nickname="Timer")
    res = await command.do_process(msg, [])
    assert res == {"playlist": "新电台"}
    command._handle_collection.assert_called_once_with(msg)


@pytest.mark.asyncio
async def test_playlist_command_blocked_when_other_user_playing(clean_info_manager):
    info_manager = clean_info_manager
    info_manager.player_name = "不约儿童🐏🐏"
    info_manager.update_online_users(["不约儿童🐏🐏", "Joyer"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    command = PlaylistCommand(mock_controller)

    msg = MessageInfo(content="/playlist 周杰伦", nickname="Timer")
    res = await command.do_process(msg, ["周杰伦"])
    assert res == {"error": "不约儿童🐏🐏 正在播放歌单，请等待"}


@pytest.mark.asyncio
async def test_album_command_blocked_when_other_user_playing(clean_info_manager):
    info_manager = clean_info_manager
    info_manager.player_name = "不约儿童🐏🐏"
    info_manager.update_online_users(["不约儿童🐏🐏", "Joyer"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    command = AlbumCommand(mock_controller)

    msg = MessageInfo(content="/album 范特西", nickname="Timer")
    res = await command.do_process(msg, ["范特西"])
    assert res == {"error": "不约儿童🐏🐏 正在播放歌单，请等待"}


@pytest.mark.asyncio
async def test_singer_command_blocked_when_other_user_playing(clean_info_manager):
    info_manager = clean_info_manager
    info_manager.player_name = "不约儿童🐏🐏"
    info_manager.update_online_users(["不约儿童🐏🐏", "Joyer"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    command = SingerCommand(mock_controller)

    msg = MessageInfo(content="/singer 周杰伦", nickname="Timer")
    res = await command.do_process(msg, ["周杰伦"])
    assert res == {"error": "不约儿童🐏🐏 正在播放歌单，请等待"}


@pytest.mark.asyncio
async def test_singer_command_allowed_sets_player_name(clean_info_manager):
    info_manager = clean_info_manager
    info_manager.player_name = None

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    command = SingerCommand(mock_controller)
    command.play_singer = MagicMock(return_value={"playlist": "张天赋"})

    msg = MessageInfo(content="/singer 张天赋", nickname="张三")
    res = await command.do_process(msg, ["张天赋"])
    assert res == {"playlist": "张天赋"}
    assert info_manager.player_name == "张三"


@pytest.mark.asyncio
async def test_album_command_allowed_sets_player_name(clean_info_manager):
    info_manager = clean_info_manager
    info_manager.player_name = None

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    command = AlbumCommand(mock_controller)
    command.play_album = MagicMock(return_value={"playlist": "范特西"})

    msg = MessageInfo(content="/album 范特西", nickname="张三")
    res = await command.do_process(msg, ["范特西"])
    assert res == {"playlist": "范特西"}
    assert info_manager.player_name == "张三"


@pytest.mark.asyncio
async def test_playlist_command_allowed_sets_player_name(clean_info_manager):
    info_manager = clean_info_manager
    info_manager.player_name = None

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    command = PlaylistCommand(mock_controller)
    command.play_playlist = MagicMock(return_value={"playlist": "流行歌单"})

    msg = MessageInfo(content="/playlist 流行歌单", nickname="张三")
    res = await command.do_process(msg, ["流行歌单"])
    assert res == {"playlist": "流行歌单"}
    assert info_manager.player_name == "张三"
