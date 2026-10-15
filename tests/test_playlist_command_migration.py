"""`:playlist` 两条路径的分工（#434）。

迁移后这条命令有两段截然不同的语义，测试把它们分开钉住：

| 路径 | 是什么 | 该不该碰麦克风 |
|------|--------|----------------|
| `:playlist <query>` | 切歌：搜歌单、点开、整张播放 | 该（引擎 `PlaybackMuting.guard` 负责） |
| `:playlist` | 查询：读当前播放队列 | 不该 |

测试面只有命令的 `do_process`/`playback_muting_applies` 与 `CommandManager` 真正
使用的那层静音上下文；引擎与守护用真模块，UI 用 `InMemoryMusicUIDriver`，麦克风
用记录动作的替身。因此「裸 `:playlist` 不闭麦」是观察出来的，不是注释出来的。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.commands.playlist import PlaylistCommand
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.models import PlaybackMode, PlaybackTrack
from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.managers.playlist_adoption import PlaylistAdoption
from ushareiplay.models.message_info import MessageInfo
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver

QUEUE_TEXT = "似是故人来 - 梅艳芳\n如风 - 王菲"


class _QueueReader:
    """裸 `:playlist` 直接读队列：只暴露 `get_playlist_info()`。

    刻意不留别的方法 —— 查询路径多走一步（例如误调 `query_music`）就会以
    AttributeError 暴露出来。
    """

    def __init__(self, info=None):
        self.info = info if info is not None else {"playlist": QUEUE_TEXT}
        self.reads = 0

    def get_playlist_info(self):
        self.reads += 1
        return self.info


class _RecordingMicManager:
    """记录真实开闭麦动作，供「麦克风未被触碰」断言使用。"""

    def __init__(self, journal, mic_state=True):
        self.journal = journal
        self._state = mic_state

    def state(self):
        return self._state

    def set_active(self, enable):
        self.journal.append("mute" if not enable else "unmute")
        self._state = enable
        return {"state": "1" if self._state else "0"}

    def ensure_active(self):
        self.journal.append("restore")
        self._state = True
        return {"state": "1"}


class _ReadinessProbe:
    """就绪探针替身：不发 `dumpsys`，也不真的睡眠。"""

    def __init__(self):
        self.waits = []

    def wait_for_playback_ready(self, expected_song=None, timeout=5.0, settling_delay=0.3):
        self.waits.append(expected_song)
        return True


def _build_engine(*, protection_error=None, driver=None, journal=None):
    """真实引擎 + 真实守护/静音模块；只有 UI 与麦克风是替身。

    `journal` 是麦克风动作与 UI 动作共用的时间线 —— 「守护拒绝时一个 UI 动作都
    不该发生、麦克风也不该响一下」这类断言考的就是它。
    """
    journal = journal if journal is not None else []
    driver = driver or InMemoryMusicUIDriver(journal=journal)

    async def _check(requester, config=None):
        return protection_error

    info = SimpleNamespace(
        player_name=None,
        current_playlist_name=None,
        check_playlist_protection=_check,
    )

    room_profile = SimpleNamespace(titles=[], topics=[])

    def _set_title(title):
        room_profile.titles.append(title)

    def _set_topic(topic):
        room_profile.topics.append(topic)

    room_profile.set_title = _set_title
    room_profile.set_topic = _set_topic

    adoption = PlaylistAdoption.instance()
    adoption._info = info
    adoption._room_profile = room_profile
    adoption._music = SimpleNamespace(list_mode=None, no_skip=0)

    MusicManager.initialize(ui_driver=driver)
    PlaybackMuting.initialize(
        SimpleNamespace(logger=MagicMock(), config={}),
        _ReadinessProbe(),
        _RecordingMicManager(journal),
    )

    return SimpleNamespace(
        driver=driver, info=info, room_profile=room_profile, journal=journal
    )


def _command(handler=None):
    handler = handler if handler is not None else _QueueReader()
    return PlaylistCommand(
        SimpleNamespace(
            soul_handler=SimpleNamespace(logger=MagicMock()),
            music_handler=handler,
            config={},
        )
    )


def _message(query: str = "/playlist"):
    return MessageInfo(content=query, nickname="小明")


# ---------------------------------------------------------------------------
# :playlist <query> —— 切歌，交给引擎
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_playlist_with_a_query_delegates_to_the_playback_engine(initialized_test_singletons):
    driver = InMemoryMusicUIDriver(
        playlists={PlaybackMode.PLAYLIST: "学习|英语"},
        tracks={PlaybackMode.PLAYLIST: PlaybackTrack(song="似是故人来", singer="梅艳芳")},
    )
    _build_engine(driver=driver)

    result = await _command().do_process(_message("/playlist 学习"), ["学习", "歌单"])

    assert len(driver.requests) == 1
    request = driver.requests[0]
    assert request.mode is PlaybackMode.PLAYLIST
    assert request.query == "学习 歌单"
    assert request.requester == "小明"


@pytest.mark.asyncio
async def test_playlist_with_a_query_returns_the_formatted_response(initialized_test_singletons):
    """`:playlist` 的回复模板是纯 `{playlist}`，渲染的必须是引擎交回来的那一份。

    卡上原文与队列文本的分工在 `tests/test_qqmusic_ui_driver.py` 里按驱动切片
    断言；这里只看命令不吞掉它、也不自己拼 dict。
    """
    driver = InMemoryMusicUIDriver(playlists={PlaybackMode.PLAYLIST: QUEUE_TEXT})
    _build_engine(driver=driver)

    result = await _command().do_process(_message("/playlist 学习"), ["学习"])

    assert "error" not in result
    assert result["playlist"] == QUEUE_TEXT


@pytest.mark.asyncio
async def test_playlist_adopts_the_room_state_through_the_engine(initialized_test_singletons):
    """房间同步归引擎的流水线：驱动读到的事实由引擎交给 `PlaylistAdoption`。"""
    driver = InMemoryMusicUIDriver(
        playlists={PlaybackMode.PLAYLIST: "学习|英语"},
        titles={PlaybackMode.PLAYLIST: "学习"},
        topics={PlaybackMode.PLAYLIST: "英语"},
    )
    engine = _build_engine(driver=driver)

    await _command().do_process(_message("/playlist 学习"), ["学习"])

    assert engine.info.player_name == "小明"
    assert engine.info.current_playlist_name == "学习|英语"
    assert engine.room_profile.titles == ["学习"]
    assert engine.room_profile.topics == ["英语"]


# ---------------------------------------------------------------------------
# 裸 :playlist —— 只读，不闭麦、不换歌
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bare_playlist_reads_the_current_queue(initialized_test_singletons):
    _build_engine()
    handler = _QueueReader()

    result = await _command(handler).do_process(_message("/playlist"), [])

    assert result == {"playlist": QUEUE_TEXT}
    assert handler.reads == 1


@pytest.mark.asyncio
async def test_bare_playlist_never_reaches_the_playback_engine(initialized_test_singletons):
    """查询路径不该构造播放请求：驱动一次都不该被叫到。"""
    driver = InMemoryMusicUIDriver()
    _build_engine(driver=driver)

    await _command().do_process(_message("/playlist"), [])

    assert driver.requests == []


@pytest.mark.asyncio
async def test_bare_playlist_leaves_the_microphone_completely_alone(initialized_test_singletons):
    """麦克风时间线上一个动作都不该有 —— 连「本来就没开麦所以没动」都不算。"""
    engine = _build_engine()

    await _command().do_process(_message("/playlist"), [])

    assert engine.journal == []


def test_bare_playlist_declares_no_command_level_muting(initialized_test_singletons):
    """命令级闭麦发生在守护之前；查询路径既不切歌也不该占用麦克风。"""
    command = _command()

    assert command.playback_muting is True, "切歌路径仍然参与静音"
    assert command.playback_muting_applies(["学习"]) is True
    assert command.playback_muting_applies([]) is False


def test_command_manager_keeps_the_microphone_out_of_a_bare_playlist_query(
    initialized_test_singletons,
):
    """走 `CommandManager` 真正使用的那层上下文：`retry: true` 之外也不该有静音。"""
    journal = []
    _build_engine(journal=journal)
    command = _command()
    manager = CommandManager.instance()

    with manager.playback_muting_guard(command, {"parameters": []}):
        pass

    assert journal == []


@pytest.mark.asyncio
async def test_bare_playlist_is_idempotent_across_the_retry(initialized_test_singletons):
    """`playlist` 在 config.yaml 里是 `retry: true`：失败会被再跑一次。

    查询必须可重复调用且给出同一份答案 —— 重试不能把房间状态搅乱。
    """
    driver = InMemoryMusicUIDriver()
    engine = _build_engine(driver=driver)
    handler = _QueueReader(info={"error": "No songs found in playlist"})
    command = _command(handler)

    first = await command.do_process(_message("/playlist"), [])
    second = await command.do_process(_message("/playlist"), [])

    assert first == second == {"error": "No songs found in playlist"}
    assert driver.requests == []
    assert engine.journal == []


# ---------------------------------------------------------------------------
# 守护拒绝：麦克风与 UI 都不该被触碰
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rejected_playlist_switch_leaves_the_microphone_untouched(
    initialized_test_singletons,
):
    """守护拒绝发生在引擎闭麦之前：被拒绝的那一次不该让房间里的人听见静音。"""
    driver = InMemoryMusicUIDriver()
    engine = _build_engine(
        driver=driver,
        protection_error={"error": "小红 正在播放歌单，请等待"},
        journal=[],
    )

    result = await _command().do_process(_message("/playlist 学习"), ["学习"])

    assert result == {"error": "小红 正在播放歌单，请等待"}
    assert driver.requests == [], "守护拒绝时不该有任何 UI 动作"
    assert engine.journal == [], "守护拒绝时不该有闭麦或开麦"
