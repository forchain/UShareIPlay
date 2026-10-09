import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

from ushareiplay.commands.info import InfoCommand
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.state.online_list_scraper import OnlineListScraper
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def reset_singletons():
    from ushareiplay.managers.info_manager import InfoManager
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
    from ushareiplay.state.playlist_state import PlaylistState
    RoomState.reset_instance()
    PresenceTracker.reset_instance()
    OnlineListScraper.reset_instance()
    InfoManager.reset_instance()
    PlaybackBroadcaster.reset_instance()
    PlaylistState.reset_instance()
    PlaybackBroadcaster.initialize()
    PlaylistState.initialize()
    yield
    RoomState.reset_instance()
    PresenceTracker.reset_instance()
    OnlineListScraper.reset_instance()
    InfoManager.reset_instance()
    PlaybackBroadcaster.reset_instance()
    PlaylistState.reset_instance()


@pytest.mark.asyncio
async def test_info_command_and_presence_not_empty_when_count_diverges():
    """
    复现 Bug：
    当房间人数（例如 3 人，含在麦用户或自身）与在线列表抽屉抓取到的人数（例如 2 人）不一致时，
    refresh_online_users 不得放弃更新导致 PresenceTracker 变空、info 命令显示「列表暂未更新」。
    同时，在更新在线用户时必须输出在线人物列表日志（INFO 级别）。
    """
    room_state = RoomState.initialize()
    room_state.user_count = 3

    info_logs = []
    logger = SimpleNamespace(
        info=lambda msg: info_logs.append(str(msg)),
        debug=lambda msg: None,
        warning=lambda msg: None,
        error=lambda msg: None,
        critical=lambda msg: None,
    )

    presence_tracker = PresenceTracker.initialize()
    presence_tracker._logger = logger

    scraper = OnlineListScraper.initialize()
    scraper._logger = logger
    scraper._handler = SimpleNamespace(
        logger=logger,
        element_finder=MagicMock(),
        gesture_handler=MagicMock(),
        controller=None,
    )

    # 抽屉中抓取到 2 人（例如在麦用户不在抽屉列表中）
    scraped_users = {"Alice", "Bob"}
    with patch.object(scraper, "_scrape_online_user_names", return_value=(scraped_users, 3)):
        # 传入 target_count=3
        success = await scraper.refresh_online_users(target_count=3)

    # 1. 刷新不应失败或抛弃更新
    assert success is True, "refresh_online_users should succeed and not abandon update"

    # 2. PresenceTracker 必须更新且非空
    online_users = presence_tracker.get_online_users()
    assert "Alice" in online_users
    assert "Bob" in online_users

    from ushareiplay.managers.info_manager import InfoManager
    info_manager = InfoManager.initialize()
    info_manager._logger = logger
    info_manager._party_manager = SimpleNamespace(init_time=None)

    # 3. info 命令必须正常输出在线用户，而不是「列表暂未更新」
    soul_handler = SimpleNamespace(logger=logger, log_error=MagicMock())
    cmd = InfoCommand(SimpleNamespace(soul_handler=soul_handler, music_handler=None, logger=logger))
    with patch("ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance", return_value=None):
        msg = MessageInfo(content=":info", nickname="Alice")
        res = await cmd.process(msg, [])
        assert res["online_users"] != "列表暂未更新"
        assert "Alice" in res["online_users"]

    # 4. 在线人数变更时必须在 INFO 日志中输出在线人物列表
    assert any("Online users:" in log or "在线用户" in log for log in info_logs), (
        f"Expected online users list in info logs, got: {info_logs}"
    )
