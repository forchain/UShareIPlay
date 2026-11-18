"""Next Queue 状态测试（Ticket #520）。

Next Queue 是三处行为的共同状态：`:next` 记录一次待播、非首次曲目切换消费一次、
连续歌单被采纳时清空。这里在接口层验证状态语义，以及四个接入点各自的行为。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.modules.playback.use_cases import PlaylistSession


def _fake_logger(logs=None):
    logs = logs if logs is not None else []
    return SimpleNamespace(
        info=lambda *_a, **_k: logs.append(_a),
        warning=lambda *_a, **_k: None,
        error=lambda *_a, **_k: None,
    ), logs


@pytest.fixture
def playlist_session():
    return PlaylistSession(logger=_fake_logger()[0])


# --------------------------------------------------------------------------
# PlaylistSession：记录 / 消费 / 清空
# --------------------------------------------------------------------------

def test_record_next_increments_and_tracks_each_contributor(playlist_session):
    playlist_session.record_next("Alice")
    assert playlist_session.pending_next_count == 1
    assert playlist_session.next_queue_contributors == {"Alice"}

    playlist_session.record_next("Bob")
    assert playlist_session.pending_next_count == 2
    assert playlist_session.next_queue_contributors == {"Alice", "Bob"}


def test_next_queue_starts_empty(playlist_session):
    assert playlist_session.pending_next_count == 0
    assert playlist_session.next_queue_contributors == set()


def test_consume_track_decrements_and_clamps_at_zero(playlist_session):
    playlist_session.record_next("Alice")
    playlist_session.record_next("Alice")

    playlist_session.consume_track()
    assert playlist_session.pending_next_count == 1

    playlist_session.consume_track()
    assert playlist_session.pending_next_count == 0

    playlist_session.consume_track()
    assert playlist_session.pending_next_count == 0


def test_reaching_zero_clears_the_contributors(playlist_session):
    playlist_session.record_next("Alice")
    playlist_session.record_next("Bob")

    playlist_session.consume_track()
    assert playlist_session.next_queue_contributors == {"Alice", "Bob"}

    playlist_session.consume_track()
    assert playlist_session.pending_next_count == 0
    assert playlist_session.next_queue_contributors == set()


def test_clear_next_queue_resets_count_and_contributors(playlist_session):
    playlist_session.record_next("Alice")
    playlist_session.record_next("Bob")

    playlist_session.clear_next_queue()

    assert playlist_session.pending_next_count == 0
    assert playlist_session.next_queue_contributors == set()


def test_consume_logs_only_when_the_queue_empties(playlist_session):
    logs = []
    playlist_session._logger, _ = _fake_logger(logs)

    playlist_session.record_next("Alice")
    playlist_session.record_next("Bob")
    logs.clear()

    playlist_session.consume_track()  # 2 -> 1：队列仍在，不应刷日志
    assert logs == []

    playlist_session.consume_track()  # 1 -> 0：队列清空，属于行为触发
    assert logs


# --------------------------------------------------------------------------
# PlaylistSession.adopt：采纳连续歌单时清空 Next Queue
# --------------------------------------------------------------------------

@pytest.fixture
def stateful_info_manager(playlist_session):
    from tests.legacy_state import PresenceTracker, RoomState
    from ushareiplay.modules.room import InfoManager

    logger, _ = _fake_logger()
    return InfoManager(
        room_state=RoomState.instance() if RoomState.is_initialized() else RoomState.initialize(),
        presence=PresenceTracker.instance() if PresenceTracker.is_initialized() else PresenceTracker.initialize(),
        playlist=playlist_session,
        logger=logger,
    )


@pytest.fixture
def adoption(playlist_session):
    playlist_session._room_profile = SimpleNamespace(
        set_title=lambda _title: None, set_topic=lambda _topic: None
    )
    return playlist_session


def test_adopt_continuous_queue_clears_the_next_queue(adoption, playlist_session):
    playlist_session.record_next("Alice")
    playlist_session.record_next("Bob")

    assert adoption.adopt(requester="Carol", mode="radio", title="O Radio") is None

    assert playlist_session.pending_next_count == 0
    assert playlist_session.next_queue_contributors == set()


def test_adopt_single_song_keeps_the_next_queue(adoption, playlist_session):
    """单曲插播不是歌单切换：别人的 :next 队列不该被它清掉。"""
    playlist_session.record_next("Alice")

    assert adoption.adopt(
        requester="Carol", mode="song", title="", topic="晴天 - 周杰伦"
    ) is None

    assert playlist_session.pending_next_count == 1
    assert playlist_session.next_queue_contributors == {"Alice"}


# --------------------------------------------------------------------------
# PlaybackBroadcaster.update：非首次曲目切换消费一次
# --------------------------------------------------------------------------

@pytest.fixture
def broadcaster(playlist_session):
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster

    PlaybackBroadcaster.reset_instance()
    module = PlaybackBroadcaster.initialize(
        SimpleNamespace(logger=_fake_logger()[0]),
        playlist_session=playlist_session,
    )
    module._logger, _ = _fake_logger()
    # 广播落地的细节（Soul 消息 / 音质处理）不在这里考，只留状态消费。
    module.send_playing_message = lambda: None
    return module


def test_broadcaster_consumes_only_on_non_initial_track_changes(
    broadcaster, playlist_session
):
    playlist_session.record_next("Alice")
    playlist_session.record_next("Alice")
    broadcaster._playback_info_cache = {"song": "A", "singer": "X", "album": "Y"}

    broadcaster.update()  # 首次初始化：不消费
    assert playlist_session.pending_next_count == 2

    broadcaster._playback_info_cache = {"song": "A", "singer": "X", "album": "Y"}
    broadcaster.update()  # 曲目未变：不消费
    assert playlist_session.pending_next_count == 2

    broadcaster._playback_info_cache = {"song": "B", "singer": "X", "album": "Y"}
    broadcaster.update()  # 非首次的曲目切换：消费一次
    assert playlist_session.pending_next_count == 1
    assert playlist_session.next_queue_contributors == {"Alice"}


def test_broadcaster_does_not_consume_on_an_error_cache_entry(
    broadcaster, playlist_session
):
    """一次读取失败不是曲目切换，不能侵蚀待播计数。"""
    playlist_session.record_next("Alice")
    broadcaster._playback_info_cache = {"song": "A", "singer": "X", "album": "Y"}
    broadcaster.update()  # 首次初始化
    assert playlist_session.pending_next_count == 1

    broadcaster._playback_info_cache = {
        "error": "transient read failure",
        "song": "Unknown",
        "singer": "Unknown",
        "album": "Unknown",
    }
    broadcaster.update()

    assert playlist_session.pending_next_count == 1
    assert playlist_session.next_queue_contributors == {"Alice"}


# --------------------------------------------------------------------------
# NextCommand：只在 play_next 成功（非 error dict）时记录
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_next_command_records_a_successful_enqueue(
    stateful_info_manager, playlist_session
):
    from ushareiplay.adapters.inbound.chat.next import NextCommand
    from ushareiplay.modules.playback.use_cases import PlayNext
    from ushareiplay.models.message_info import MessageInfo

    next_driver = SimpleNamespace(play_next=MagicMock(return_value={"success": True}))
    controller = SimpleNamespace(
        soul_handler=MagicMock(),
        music_handler=next_driver,
        play_next=PlayNext(next_driver=next_driver, playlist_session=playlist_session),
    )
    command = NextCommand(controller)

    result = await command.do_process(
        MessageInfo(content="/next 晴天", nickname="Alice"), ["晴天"]
    )

    assert result == {"success": True}
    assert playlist_session.pending_next_count == 1
    assert playlist_session.next_queue_contributors == {"Alice"}


@pytest.mark.asyncio
async def test_next_command_does_not_record_when_play_next_fails(
    stateful_info_manager, playlist_session
):
    from ushareiplay.adapters.inbound.chat.next import NextCommand
    from ushareiplay.modules.playback.use_cases import PlayNext
    from ushareiplay.models.message_info import MessageInfo

    next_driver = SimpleNamespace(play_next=MagicMock(return_value={"error": "Not found"}))
    controller = SimpleNamespace(
        soul_handler=MagicMock(),
        music_handler=next_driver,
        play_next=PlayNext(next_driver=next_driver, playlist_session=playlist_session),
    )
    command = NextCommand(controller)

    result = await command.do_process(
        MessageInfo(content="/next 不存在", nickname="Alice"), ["不存在"]
    )

    assert result == {"error": "Not found"}
    assert playlist_session.pending_next_count == 0
    assert playlist_session.next_queue_contributors == set()


@pytest.mark.asyncio
async def test_next_command_does_not_record_when_the_handler_play_next_raises(
    stateful_info_manager, playlist_session
):
    """handler 的异常必须变成 error dict 再回到命令层。

    之前异常路径返回不带 'error' 的 {'song': ..., 'singer': 'unknown'}，
    于是 NextCommand 把一次失败的入队当成成功记了一笔。
    """
    from ushareiplay.adapters.inbound.chat.next import NextCommand
    from ushareiplay.adapters.outbound.appium.qq_music.qq_music_handler import QQMusicHandler
    from ushareiplay.modules.playback.use_cases import PlayNext
    from ushareiplay.models.message_info import MessageInfo

    handler = QQMusicHandler.__new__(QQMusicHandler)
    handler.logger = _fake_logger()[0]
    handler._prepare_music_playback = MagicMock(side_effect=RuntimeError("boom"))
    command = NextCommand(
        SimpleNamespace(
            soul_handler=MagicMock(),
            music_handler=handler,
            play_next=PlayNext(next_driver=handler, playlist_session=playlist_session),
        )
    )

    result = await command.do_process(
        MessageInfo(content="/next 晴天", nickname="Alice"), ["晴天"]
    )

    assert result == {"error": "Error playing next music: boom"}
    assert playlist_session.pending_next_count == 0
    assert playlist_session.next_queue_contributors == set()
