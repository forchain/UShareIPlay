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
    fake_logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    for cls in (
        RoomState,
        PresenceTracker,
        PlaylistState,
        PlaybackBroadcaster,
        OnlineListScraper,
    ):
        cls.initialize()._logger = fake_logger
    manager = InfoManager.initialize()
    manager._logger = fake_logger
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
        "soul": {
            "room_owner": "Joyer",
            "admin_users": ["Outlier", "Chainer"],
            "system_users": ["Timer", "Agent"],
        }
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
        "soul": {
            "room_owner": "Joyer",
            "admin_users": ["Outlier", "Chainer"],
            "system_users": ["Timer", "Agent"],
        }
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
        "soul": {
            "room_owner": "Joyer",
            "admin_users": ["Outlier", "Chainer"],
            "system_users": ["Timer", "Agent"],
        }
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
        "soul": {
            "room_owner": "Joyer",
            "admin_users": ["Outlier", "Chainer"],
            "system_users": ["Timer", "Agent"],
        }
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
        "soul": {
            "room_owner": "Joyer",
            "admin_users": ["Outlier", "Chainer"],
            "system_users": ["Timer", "Agent"],
        }
    }

    command = RadioCommand(mock_controller)
    command._handle_collection = MagicMock(return_value={"playlist": "新电台"})

    msg = MessageInfo(content="/radio", nickname="Timer")
    res = await command.do_process(msg, [])
    assert res == {"playlist": "新电台"}
    command._handle_collection.assert_called_once_with(msg)


@pytest.fixture
def playlist_engine(clean_info_manager):
    """:playlist 切歌路径的引擎台：真守护（InfoManager）+ 内存 UI 驱动。

    #434 之后 `:playlist <query>` 走 `MusicManager.play()`，守护因而由引擎调
    `PlaylistAdoption.guard_switch`。这里只把 UI 换成内存替身 —— 守护判定仍然
    是真的 `InfoManager.check_playlist_protection`，因此这些用例考的是「守护还
    管不管得住」，不是「命令层有没有再自己判一次」。
    """
    from ushareiplay.managers.music_manager import MusicManager
    from ushareiplay.managers.playback_muting import PlaybackMuting
    from ushareiplay.managers.playlist_adoption import PlaylistAdoption
    from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver

    driver = InMemoryMusicUIDriver()

    adoption = PlaylistAdoption.instance()
    adoption._info = clean_info_manager
    # 房名/话题的落地归 RoomProfileManager 与 Soul UI 那一层，守护用例不管它：
    # 这里给一个只记调用、不碰 UI 的替身。
    adoption._room_profile = SimpleNamespace(
        set_title=lambda title: None, set_topic=lambda topic: None
    )
    adoption._music = SimpleNamespace(list_mode=None, no_skip=0)

    MusicManager.initialize(ui_driver=driver)
    PlaybackMuting.initialize(
        SimpleNamespace(logger=SimpleNamespace(info=lambda *_a: None), config={}),
        SimpleNamespace(wait_for_playback_ready=lambda **_kw: True),
        SimpleNamespace(state=lambda: False, set_active=lambda *_a: None,
                        ensure_active=lambda: None),
    )
    return driver


@pytest.mark.asyncio
async def test_playlist_command_blocked_when_other_user_playing(clean_info_manager, playlist_engine):
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
    # 被守护拦下时一个 UI 动作都不该发生
    assert playlist_engine.requests == []


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
@pytest.mark.parametrize(
    ("command_class", "play_method", "content", "parameters", "result"),
    [
        (SingerCommand, "play_singer", "/singer 张天赋", ["张天赋"], {"playlist": "张天赋"}),
        (AlbumCommand, "play_album", "/album 范特西", ["范特西"], {"playlist": "范特西"}),
    ],
)
async def test_allowed_commands_hand_the_requester_to_the_play_step(
    clean_info_manager, command_class, play_method, content, parameters, result
):
    """守护放行后，请求者被交给播放方法 —— 播放在成功时把它交给 PlaylistAdoption 记录。

    命令不再自己写 player_name（那次写入现在归 PlaylistAdoption.adopt），
    因此这里断言的是「请求者被正确传下去」，播放者写入本身由
    tests/test_playlist_adoption.py 在模块接口层覆盖。

    `:playlist` 不在此列：#434 之后它把请求交给引擎，没有可 mock 的播放方法了；
    请求者的传递由下面那条用例在引擎入口上断言。
    """
    info_manager = clean_info_manager
    info_manager.player_name = None

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    command = command_class(mock_controller)
    play = MagicMock(return_value=result)
    setattr(command, play_method, play)

    msg = MessageInfo(content=content, nickname="张三")
    res = await command.do_process(msg, parameters)

    assert res == result
    play.assert_called_once_with(parameters[0], "张三")


@pytest.mark.asyncio
async def test_playlist_hands_the_requester_to_the_playback_engine(
    clean_info_manager, playlist_engine
):
    """`:playlist <query>` 迁移进引擎后，请求者在 `PlaybackRequest.requester` 上。"""
    clean_info_manager.player_name = None

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    command = PlaylistCommand(mock_controller)

    await command.do_process(MessageInfo(content="/playlist 流行歌单", nickname="张三"), ["流行歌单"])

    assert len(playlist_engine.requests) == 1
    assert playlist_engine.requests[0].requester == "张三"
    assert clean_info_manager.player_name == "张三", "请求者最终写进房间播放者"


@pytest.mark.asyncio
async def test_admin_and_owner_can_override_user_playlist(clean_info_manager, playlist_engine):
    """
    当普通用户正在播放且在线时，管理员（Outlier/Chainer）、房主（Joyer）以及控制台（Console）
    可以突破守护，执行切歌操作。
    """
    info_manager = clean_info_manager
    info_manager.player_name = "普通用户"
    info_manager.update_online_users(["普通用户", "Joyer", "Outlier"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    mock_controller.config = {
        "soul": {
            "room_owner": "Joyer",
            "admin_users": ["Outlier", "Chainer"],
            "system_users": ["Timer", "Agent"],
        }
    }

    command = PlaylistCommand(mock_controller)

    # 1. 管理员 Outlier 切歌 -> 允许突破保护
    msg = MessageInfo(content="/playlist 管理员歌单", nickname="Outlier")
    res = await command.do_process(msg, ["管理员歌单"])
    assert "error" not in res

    # 2. 房主 Joyer 切歌 -> 允许突破保护
    info_manager.player_name = "普通用户"
    msg_owner = MessageInfo(content="/playlist 房主歌单", nickname="Joyer")
    res_owner = await command.do_process(msg_owner, ["房主歌单"])
    assert "error" not in res_owner

    # 3. 管理员 Chainer 切歌 -> 允许突破保护
    info_manager.player_name = "普通用户"
    msg_admin2 = MessageInfo(content="/playlist 管理员歌单2", nickname="Chainer")
    res_admin2 = await command.do_process(msg_admin2, ["管理员歌单2"])
    assert "error" not in res_admin2


@pytest.mark.asyncio
async def test_normal_user_can_play_when_admin_or_owner_is_playing(
    clean_info_manager, playlist_engine
):
    """
    当管理员（Outlier）或房主（Joyer）正在播放歌单时，无需保护，普通用户点歌可自由切入。
    """
    info_manager = clean_info_manager
    info_manager.player_name = "Outlier"
    info_manager.update_online_users(["普通用户", "Outlier"])

    mock_controller = MagicMock()
    mock_controller.soul_handler = MagicMock()
    mock_controller.music_handler = MagicMock()
    mock_controller.config = {
        "soul": {
            "room_owner": "Joyer",
            "admin_users": ["Outlier", "Chainer"],
            "system_users": ["Timer", "Agent"],
        }
    }

    command = PlaylistCommand(mock_controller)

    msg = MessageInfo(content="/playlist 用户点歌", nickname="普通用户")
    res = await command.do_process(msg, ["用户点歌"])
    assert "error" not in res

