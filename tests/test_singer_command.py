"""`:singer` 迁进 `MusicManager.play()` 之后的命令形态（#437）。

命令层现在只剩两件事：把参数解析成一个 `PlaybackRequest`，把引擎交回来的结果
原样变成 `as_response()`。查歌手、点卡片、播放全部、读队列全在 `QQMusicUIDriver`
（见 `tests/test_singer_album_seam.py`）。

守护、静音与房间同步都由引擎流水线负责，因此命令层不再自己判一次守护，也不再
声明 `playback_muting` —— 命令级闭麦发生在守护之前，被守护拒绝的那一次也会在
房间里响一次无来由的静音（ADR-0007 把闭麦边界定在真正的切歌过程上）。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.commands.singer import SingerCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.models import PlaybackMode, PlaybackTrack
from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.managers.playlist_adoption import PlaylistAdoption
from ushareiplay.models.message_info import MessageInfo
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver

QUEUE_TEXT = "简单爱 - 周杰伦\n爱在西元前 - 周杰伦"


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
    guards = []

    async def _check(requester, config=None):
        guards.append(requester)
        return protection_error

    info = SimpleNamespace(
        player_name=None,
        current_playlist_name=None,
        check_playlist_protection=_check,
    )
    room_profile = SimpleNamespace(titles=[], topics=[])
    room_profile.set_title = room_profile.titles.append
    room_profile.set_topic = room_profile.topics.append

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
        driver=driver,
        info=info,
        room_profile=room_profile,
        journal=journal,
        guards=guards,
    )


def _command():
    return SingerCommand(
        SimpleNamespace(
            soul_handler=SimpleNamespace(logger=MagicMock()),
            music_handler=MagicMock(),
            config={},
        )
    )


def _message(content="/singer 张天赋"):
    return MessageInfo(content=content, nickname="小明")


@pytest.mark.asyncio
async def test_singer_delegates_to_the_playback_engine(initialized_test_singletons):
    """`:singer <query>` 只构造请求并交给引擎：模式、查询词、请求者各归各位。"""
    driver = InMemoryMusicUIDriver(
        tracks={PlaybackMode.SINGER: PlaybackTrack(song="简单爱", singer="周杰伦")}
    )
    _build_engine(driver=driver)

    await _command().do_process(_message(), ["张", "天赋"])

    assert len(driver.requests) == 1
    request = driver.requests[0]
    assert request.mode is PlaybackMode.SINGER
    assert request.query == "张 天赋"
    assert request.requester == "小明"


@pytest.mark.asyncio
async def test_singer_returns_the_queue_the_engine_reported(initialized_test_singletons):
    """`:singer` 的回复模板是纯 `{playlist}`，渲染的必须是引擎交回来的那一份。"""
    driver = InMemoryMusicUIDriver(playlists={PlaybackMode.SINGER: QUEUE_TEXT})
    _build_engine(driver=driver)

    result = await _command().do_process(_message(), ["张天赋"])

    assert "error" not in result
    assert result["playlist"] == QUEUE_TEXT


@pytest.mark.asyncio
async def test_singer_adopts_the_room_state_through_the_engine(initialized_test_singletons):
    """房间同步归引擎的流水线：驱动观察到的事实由引擎交给 `PlaylistAdoption`。"""
    driver = InMemoryMusicUIDriver(
        playlists={PlaybackMode.SINGER: "张天赋"},
        titles={PlaybackMode.SINGER: "张天赋"},
        topics={PlaybackMode.SINGER: "张天赋"},
    )
    engine = _build_engine(driver=driver)

    await _command().do_process(_message(), ["张天赋"])

    assert engine.info.player_name == "小明"
    assert engine.info.current_playlist_name == "张天赋"
    assert engine.room_profile.titles == ["张天赋"]
    assert engine.room_profile.topics == ["张天赋"]


@pytest.mark.asyncio
async def test_singer_guards_exactly_once_through_the_engine(initialized_test_singletons):
    """守护只在引擎里判一次。

    命令层自己那一次判不出是谁调的（它与引擎共用同一个 `PlaylistAdoption`
    单例），能断言的是**次数**：迁移前命令判一次、引擎再判一次，同一次请求会被
    判两遍，弹两次窗，还丢掉命令侧传下去的 config 变体。
    """
    driver = InMemoryMusicUIDriver()
    engine = _build_engine(driver=driver)

    await _command().do_process(_message(), ["张天赋"])

    assert engine.guards == ["小明"]
    assert len(driver.requests) == 1


def test_singer_declares_no_command_level_muting(initialized_test_singletons):
    """命令级闭麦发生在守护之前，被守护拒绝的切歌也会响一次无来由的静音。"""
    command = _command()

    assert command.playback_muting is False
    assert "playback_muting_applies" not in vars(type(command))


@pytest.mark.asyncio
async def test_a_rejected_singer_switch_leaves_the_microphone_untouched(
    initialized_test_singletons,
):
    """守护拒绝发生在引擎闭麦之前：被拒绝的那一次不该让房间里的人听见静音。"""
    engine = _build_engine(
        protection_error={"error": "小红 正在播放歌单，请等待"},
        journal=[],
    )

    result = await _command().do_process(_message(), ["张天赋"])

    assert result == {"error": "小红 正在播放歌单，请等待"}
    assert engine.driver.requests == [], "守护拒绝时不该有任何 UI 动作"
    assert engine.journal == [], "守护拒绝时不该有闭麦或开麦"
