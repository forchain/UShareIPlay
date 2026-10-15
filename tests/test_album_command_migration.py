"""`:album` 迁进 `MusicManager.play()` 之后的命令形态（#437）。

与 `:singer` 同一条流水线，命令层只做两件事：解析参数、把 `as_response()` 交回去。
`:album` 多一条语义 —— 不带参数时「播现在这首所在的专辑」。查询词怎么补由驱动
决定（只有驱动知道 QQ Music 的专辑检索认哪几段文字），因此命令层原样把空查询词
递进去，不在这里读播放信息。

引擎与守护用真模块，UI 用 `InMemoryMusicUIDriver`，麦克风用记录动作的替身。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.commands.album import AlbumCommand
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
    """真实引擎 + 真实守护/静音模块；只有 UI 与麦克风是替身。"""
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
    return AlbumCommand(
        SimpleNamespace(
            soul_handler=SimpleNamespace(logger=MagicMock()),
            music_handler=MagicMock(),
            config={},
        )
    )


def _message(content="/album 范特西"):
    return MessageInfo(content=content, nickname="小明")


@pytest.mark.asyncio
async def test_album_delegates_to_the_playback_engine(initialized_test_singletons):
    driver = InMemoryMusicUIDriver(
        tracks={PlaybackMode.ALBUM: PlaybackTrack(song="简单爱", singer="周杰伦")}
    )
    _build_engine(driver=driver)

    await _command().do_process(_message(), ["范", "特西"])

    assert len(driver.requests) == 1
    request = driver.requests[0]
    assert request.mode is PlaybackMode.ALBUM
    assert request.query == "范 特西"
    assert request.requester == "小明"


@pytest.mark.asyncio
async def test_bare_album_hands_the_empty_query_to_the_driver(
    initialized_test_singletons,
):
    """`:album` 不带参数 = 播现在这首所在的专辑。

    查询词怎么补是 UI 侧的事（要读当前播放、再拼成 QQ Music 认得的检索词），
    命令层原样把空查询词递进去 —— 它若自己读一次播放信息，同一次播放就会被读两遍。
    """
    driver = InMemoryMusicUIDriver()
    _build_engine(driver=driver)

    await _command().do_process(_message("/album"), [])

    assert driver.requests[0].query == ""


@pytest.mark.asyncio
async def test_album_returns_the_queue_the_engine_reported(initialized_test_singletons):
    """`:album` 的回复模板是纯 `{playlist}`，渲染的必须是引擎交回来的那一份。"""
    driver = InMemoryMusicUIDriver(playlists={PlaybackMode.ALBUM: QUEUE_TEXT})
    _build_engine(driver=driver)

    result = await _command().do_process(_message(), ["范特西"])

    assert "error" not in result
    assert result["playlist"] == QUEUE_TEXT


@pytest.mark.asyncio
async def test_album_adopts_the_room_state_through_the_engine(initialized_test_singletons):
    """房间话题是专辑名而不是队列首行 —— 只有驱动在专辑卡上读得到。"""
    driver = InMemoryMusicUIDriver(
        playlists={PlaybackMode.ALBUM: "周杰伦 - 范特西"},
        titles={PlaybackMode.ALBUM: "周杰伦"},
        topics={PlaybackMode.ALBUM: "范特西"},
    )
    engine = _build_engine(driver=driver)

    await _command().do_process(_message(), ["范特西"])

    assert engine.info.player_name == "小明"
    assert engine.info.current_playlist_name == "周杰伦 - 范特西"
    assert engine.room_profile.titles == ["周杰伦"]
    assert engine.room_profile.topics == ["范特西"]


@pytest.mark.asyncio
async def test_album_guards_exactly_once_through_the_engine(initialized_test_singletons):
    """守护只在引擎里判一次（详见 `tests/test_singer_command.py` 里的同款用例）。"""
    driver = InMemoryMusicUIDriver()
    engine = _build_engine(driver=driver)

    await _command().do_process(_message(), ["范特西"])

    assert engine.guards == ["小明"]
    assert len(driver.requests) == 1


def test_album_declares_no_command_level_muting(initialized_test_singletons):
    """命令级闭麦发生在守护之前，被守护拒绝的切歌也会响一次无来由的静音。"""
    command = _command()

    assert command.playback_muting is False
    assert "playback_muting_applies" not in vars(type(command))


@pytest.mark.asyncio
async def test_a_rejected_album_switch_leaves_the_microphone_untouched(
    initialized_test_singletons,
):
    """守护拒绝发生在引擎闭麦之前：被拒绝的那一次不该让房间里的人听见静音。"""
    engine = _build_engine(
        protection_error={"error": "小红 正在播放歌单，请等待"},
        journal=[],
    )

    result = await _command().do_process(_message(), ["范特西"])

    assert result == {"error": "小红 正在播放歌单，请等待"}
    assert engine.driver.requests == [], "守护拒绝时不该有任何 UI 动作"
    assert engine.journal == [], "守护拒绝时不该有闭麦或开麦"
