"""Next Queue 状态测试（Ticket #520）。

Next Queue 是三处行为的共同状态：`:next` 记录一次待播、非首次曲目切换消费一次、
连续歌单被采纳时清空。这里在接口层验证状态语义，以及四个接入点各自的行为。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.state.playlist_state import PlaylistState


def _fake_logger(logs=None):
    logs = logs if logs is not None else []
    return SimpleNamespace(
        info=lambda *_a, **_k: logs.append(_a),
        warning=lambda *_a, **_k: None,
        error=lambda *_a, **_k: None,
    ), logs


@pytest.fixture
def playlist_state():
    PlaylistState.reset_instance()
    state = PlaylistState.initialize()
    state._logger, _ = _fake_logger()
    return state


# --------------------------------------------------------------------------
# PlaylistState：记录 / 消费 / 清空
# --------------------------------------------------------------------------

def test_record_next_increments_and_tracks_each_contributor(playlist_state):
    playlist_state.record_next("Alice")
    assert playlist_state.pending_next_count == 1
    assert playlist_state.next_queue_contributors == {"Alice"}

    playlist_state.record_next("Bob")
    assert playlist_state.pending_next_count == 2
    assert playlist_state.next_queue_contributors == {"Alice", "Bob"}


def test_next_queue_starts_empty(playlist_state):
    assert playlist_state.pending_next_count == 0
    assert playlist_state.next_queue_contributors == set()


def test_consume_track_decrements_and_clamps_at_zero(playlist_state):
    playlist_state.record_next("Alice")
    playlist_state.record_next("Alice")

    playlist_state.consume_track()
    assert playlist_state.pending_next_count == 1

    playlist_state.consume_track()
    assert playlist_state.pending_next_count == 0

    playlist_state.consume_track()
    assert playlist_state.pending_next_count == 0


def test_reaching_zero_clears_the_contributors(playlist_state):
    playlist_state.record_next("Alice")
    playlist_state.record_next("Bob")

    playlist_state.consume_track()
    assert playlist_state.next_queue_contributors == {"Alice", "Bob"}

    playlist_state.consume_track()
    assert playlist_state.pending_next_count == 0
    assert playlist_state.next_queue_contributors == set()


def test_clear_next_queue_resets_count_and_contributors(playlist_state):
    playlist_state.record_next("Alice")
    playlist_state.record_next("Bob")

    playlist_state.clear_next_queue()

    assert playlist_state.pending_next_count == 0
    assert playlist_state.next_queue_contributors == set()


def test_consume_logs_only_when_the_queue_empties(playlist_state):
    logs = []
    playlist_state._logger, _ = _fake_logger(logs)

    playlist_state.record_next("Alice")
    playlist_state.record_next("Bob")
    logs.clear()

    playlist_state.consume_track()  # 2 -> 1：队列仍在，不应刷日志
    assert logs == []

    playlist_state.consume_track()  # 1 -> 0：队列清空，属于行为触发
    assert logs


# --------------------------------------------------------------------------
# PlaylistAdoption.adopt：采纳连续歌单时清空 Next Queue
# --------------------------------------------------------------------------

@pytest.fixture
def stateful_info_manager(playlist_state):
    from ushareiplay.managers.info_manager import InfoManager

    InfoManager.reset_instance()
    manager = InfoManager.initialize()
    manager._logger, _ = _fake_logger()
    return manager


@pytest.fixture
def adoption(stateful_info_manager):
    from ushareiplay.managers.playlist_adoption import PlaylistAdoption

    module = PlaylistAdoption.instance()
    module._info = stateful_info_manager
    module._room_profile = SimpleNamespace(
        set_title=lambda _title: None, set_topic=lambda _topic: None
    )
    module._music = SimpleNamespace(list_mode=None)
    return module


def test_adopt_continuous_queue_clears_the_next_queue(adoption, playlist_state):
    playlist_state.record_next("Alice")
    playlist_state.record_next("Bob")

    assert adoption.adopt(requester="Carol", mode="radio", title="O Radio") is None

    assert playlist_state.pending_next_count == 0
    assert playlist_state.next_queue_contributors == set()


def test_adopt_single_song_keeps_the_next_queue(adoption, playlist_state):
    """单曲插播不是歌单切换：别人的 :next 队列不该被它清掉。"""
    playlist_state.record_next("Alice")

    assert adoption.adopt(
        requester="Carol", mode="song", title="", topic="晴天 - 周杰伦"
    ) is None

    assert playlist_state.pending_next_count == 1
    assert playlist_state.next_queue_contributors == {"Alice"}


# --------------------------------------------------------------------------
# PlaybackBroadcaster.update：非首次曲目切换消费一次
# --------------------------------------------------------------------------

@pytest.fixture
def broadcaster(playlist_state):
    from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster

    PlaybackBroadcaster.reset_instance()
    module = PlaybackBroadcaster.initialize(SimpleNamespace(logger=_fake_logger()[0]))
    module._logger, _ = _fake_logger()
    # 广播落地的细节（Soul 消息 / 音质处理）不在这里考，只留状态消费。
    module.send_playing_message = lambda: None
    return module


def test_broadcaster_consumes_only_on_non_initial_track_changes(
    broadcaster, playlist_state
):
    playlist_state.record_next("Alice")
    playlist_state.record_next("Alice")
    broadcaster._playback_info_cache = {"song": "A", "singer": "X", "album": "Y"}

    broadcaster.update()  # 首次初始化：不消费
    assert playlist_state.pending_next_count == 2

    broadcaster._playback_info_cache = {"song": "A", "singer": "X", "album": "Y"}
    broadcaster.update()  # 曲目未变：不消费
    assert playlist_state.pending_next_count == 2

    broadcaster._playback_info_cache = {"song": "B", "singer": "X", "album": "Y"}
    broadcaster.update()  # 非首次的曲目切换：消费一次
    assert playlist_state.pending_next_count == 1
    assert playlist_state.next_queue_contributors == {"Alice"}


# --------------------------------------------------------------------------
# NextCommand：只在 play_next 成功（非 error dict）时记录
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_next_command_records_a_successful_enqueue(
    stateful_info_manager, playlist_state
):
    from ushareiplay.commands.next import NextCommand
    from ushareiplay.models.message_info import MessageInfo

    command = NextCommand(MagicMock())
    command.play_next = MagicMock(return_value={"success": True})

    result = await command.do_process(
        MessageInfo(content="/next 晴天", nickname="Alice"), ["晴天"]
    )

    assert result == {"success": True}
    assert playlist_state.pending_next_count == 1
    assert playlist_state.next_queue_contributors == {"Alice"}


@pytest.mark.asyncio
async def test_next_command_does_not_record_when_play_next_fails(
    stateful_info_manager, playlist_state
):
    from ushareiplay.commands.next import NextCommand
    from ushareiplay.models.message_info import MessageInfo

    command = NextCommand(MagicMock())
    command.play_next = MagicMock(return_value={"error": "Not found"})

    result = await command.do_process(
        MessageInfo(content="/next 不存在", nickname="Alice"), ["不存在"]
    )

    assert result == {"error": "Not found"}
    assert playlist_state.pending_next_count == 0
    assert playlist_state.next_queue_contributors == set()
