"""Ticket #380: 深度播放引擎 `MusicManager.play()` 的离线测试。

测试面只有一个：`MusicManager.play(request)`。守护、静音、UI 编排、房间同步
四段流水线都通过这个入口观察 —— 内部点击顺序、坐标、helper 名字都不出现在断言里。

外部依赖全部是内存替身（`tests/fakes/in_memory_music_driver.py`），因此
pytest 无需 Android 设备、Appium 服务或真实 `dumpsys` 即可跑完。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.models import (
    PlaybackMode,
    PlaybackRequest,
    PlaybackStatus,
    PlaybackTrack,
)
from ushareiplay.managers.playback.driver import MusicUIDriverPort
from ushareiplay.managers.playback.models import PlaybackOutcome
from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.managers.playlist_adoption import PlaylistAdoption
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver


class _InfoManager:
    """InfoManager 替身：歌单守护判定 + 房间播放者状态。"""

    def __init__(self, protection_error=None):
        self.protection_error = protection_error
        self.player_name = None
        self.current_playlist_name = None
        self.guard_calls = []

    async def check_playlist_protection(self, requester, config=None):
        self.guard_calls.append(requester)
        return self.protection_error


class _RoomProfileManager:
    def __init__(self):
        self.titles = []
        self.topics = []

    def set_title(self, title):
        self.titles.append(title)
        return None

    def set_topic(self, topic):
        self.topics.append(topic)
        return None


class _ReadinessProbe:
    """MediaSession 就绪探针替身：不下发 `dumpsys`，也不真的睡眠。"""

    def __init__(self, ready=True):
        self.ready = ready
        self.waits = []

    def wait_for_playback_ready(self, expected_song=None, timeout=5.0, settling_delay=0.3):
        self.waits.append(expected_song)
        return self.ready


class _RecordingMicManager:
    """记录真实开闭麦动作，并写进共享 journal 以便断言顺序。"""

    def __init__(self, journal, mic_state=True):
        self.journal = journal
        self._state = mic_state

    def state(self):
        return self._state

    def set_active(self, enable):
        self.journal.append("mute" if not enable else "unmute")
        self._state = enable
        return {"state": "1" if enable else "0"}

    def ensure_active(self):
        self.journal.append("restore")
        self._state = True
        return {"state": "1"}


def _build_engine(*, protection_error=None, driver=None, ready=True, mic_state=True, journal=None):
    """真实引擎 + 真实守护/静音模块，外部依赖全替身。

    `journal` 是麦克风动作与 UI 动作共用的时间线。传入的 driver 若未自带时间线，
    就接上同一个 —— 否则「先闭麦、再动 UI、最后开麦」的顺序无法跨替身断言。
    """
    journal = journal if journal is not None else []
    driver = driver or InMemoryMusicUIDriver(journal=journal)
    if getattr(driver, "journal", None) is None:
        driver.journal = journal

    info = _InfoManager(protection_error=protection_error)
    room_profile = _RoomProfileManager()

    adoption = PlaylistAdoption.instance()
    adoption._info = info
    adoption._room_profile = room_profile
    adoption._music = SimpleNamespace(list_mode=None, no_skip=0)

    manager = MusicManager.initialize(ui_driver=driver)
    probe = _ReadinessProbe(ready=ready)
    mic = _RecordingMicManager(journal, mic_state=mic_state)
    PlaybackMuting.initialize(
        SimpleNamespace(logger=MagicMock(), config={}),
        probe,
        mic,
    )

    return SimpleNamespace(
        manager=manager,
        driver=driver,
        info=info,
        room_profile=room_profile,
        probe=probe,
        mic=mic,
        journal=journal,
    )


# ---------------------------------------------------------------------------
# Slice 1: 播放启动
# ---------------------------------------------------------------------------


async def test_play_starts_the_requested_mode_and_reports_the_track(initialized_test_singletons):
    engine = _build_engine()
    request = PlaybackRequest.song("青花瓷 周杰伦", requester="小明")

    result = await engine.manager.play(request)

    assert result.status is PlaybackStatus.STARTED
    assert result.track.song == "青花瓷 周杰伦"
    assert result.as_response() == {
        "song": "青花瓷 周杰伦",
        "singer": "song-歌手",
        "album": "",
    }
    assert [r.mode for r in engine.driver.requests] == [PlaybackMode.SONG]


async def test_play_carries_query_channel_and_requester_to_the_driver(initialized_test_singletons):
    engine = _build_engine()
    request = PlaybackRequest(
        mode=PlaybackMode.RADIO, channel="sleep", requester="小红", room_title="O Sleep"
    )

    result = await engine.manager.play(request)

    assert result.started
    driven = engine.driver.requests[0]
    assert (driven.mode, driven.channel, driven.requester) == (
        PlaybackMode.RADIO,
        "sleep",
        "小红",
    )


async def test_play_returns_failed_when_the_driver_reports_a_ui_problem(initialized_test_singletons):
    engine = _build_engine(
        driver=InMemoryMusicUIDriver(
            failures={PlaybackMode.ALBUM: "未找到相关专辑"},
        )
    )

    result = await engine.manager.play(
        PlaybackRequest(mode=PlaybackMode.ALBUM, query="五月天", requester="小明")
    )

    assert result.status is PlaybackStatus.FAILED
    assert result.error == "未找到相关专辑"
    assert result.as_response() == {"error": "未找到相关专辑"}


async def test_play_refuses_to_run_without_a_configured_driver(initialized_test_singletons):
    """未装配 UI 驱动时必须响亮失败，而不是静默「播放成功」。"""
    engine = _build_engine()
    manager = MusicManager.instance()
    manager._ui_driver = None

    with pytest.raises(RuntimeError, match="ui_driver"):
        await manager.play(PlaybackRequest.song("任意歌曲", requester="小明"))


# ---------------------------------------------------------------------------
# Slice 2: 歌曲守护
# ---------------------------------------------------------------------------


async def test_play_rejects_an_authorized_switch_violation_with_the_guard_message(
    initialized_test_singletons,
):
    engine = _build_engine(
        protection_error={"error": "小红 正在播放歌单，请等待"},
    )

    result = await engine.manager.play(PlaybackRequest.song("稻香", requester="小明"))

    assert result.status is PlaybackStatus.REJECTED
    assert result.error == "小红 正在播放歌单，请等待"
    assert result.as_response() == {"error": "小红 正在播放歌单，请等待"}


async def test_play_never_touches_the_music_ui_when_the_guard_rejects(initialized_test_singletons):
    """被守护拒绝时不该有任何 UI 动作：这是拒绝存在的意义。"""
    engine = _build_engine(protection_error={"error": "小红 正在播放歌单，请等待"})

    await engine.manager.play(PlaybackRequest.song("稻香", requester="小明"))

    assert engine.driver.requests == []
    assert engine.journal == []


async def test_play_checks_the_guard_with_the_requester_identity(initialized_test_singletons):
    engine = _build_engine()

    await engine.manager.play(PlaybackRequest.song("稻香", requester="小明"))

    assert engine.info.guard_calls == ["小明"]


async def test_play_enforces_the_guard_for_every_mode(initialized_test_singletons):
    """守护是流水线第一段，所有模式同等受约束。"""
    engine = _build_engine(protection_error={"error": "小红 正在播放歌单，请等待"})

    for mode in PlaybackMode:
        result = await engine.manager.play(
            PlaybackRequest(mode=mode, query="任意", requester="小明")
        )
        assert result.rejected, f"{mode} 未受歌曲守护约束"

    assert engine.driver.requests == []


# ---------------------------------------------------------------------------
# Slice 3: 播放静音生命周期（ADR-0007）
# ---------------------------------------------------------------------------


async def test_play_mutes_before_ui_work_and_restores_after_playback_is_ready(
    initialized_test_singletons,
):
    engine = _build_engine()

    await engine.manager.play(PlaybackRequest.song("青花瓷", requester="小明"))

    assert engine.journal == ["mute", "ui:song", "restore"]


async def test_play_waits_for_the_requested_track_before_restoring_the_microphone(
    initialized_test_singletons,
):
    engine = _build_engine()

    await engine.manager.play(PlaybackRequest.song("青花瓷 周杰伦", requester="小明"))

    assert engine.probe.waits == ["青花瓷 周杰伦"]


async def test_play_does_not_verify_track_metadata_for_non_song_modes(initialized_test_singletons):
    """歌单/电台的队列内容调用方无从预知，拿查询词比对必然超时。"""
    engine = _build_engine()

    await engine.manager.play(
        PlaybackRequest(mode=PlaybackMode.PLAYLIST, query="轻音乐", requester="小明")
    )

    assert engine.probe.waits == [None]


async def test_play_restores_the_microphone_immediately_when_the_ui_fails(
    initialized_test_singletons,
):
    """UI 失败必须跳过就绪等待，否则房间在报错后长时间没有声音。"""
    journal = []
    engine = _build_engine(
        journal=journal,
        driver=InMemoryMusicUIDriver(failures={PlaybackMode.SONG: "未找到相关歌曲"}),
    )

    await engine.manager.play(PlaybackRequest.song("不存在的歌", requester="小明"))

    assert engine.probe.waits == []
    assert journal == ["mute", "ui:song", "restore"]


async def test_play_restores_the_microphone_when_playback_never_becomes_ready(
    initialized_test_singletons,
):
    """就绪超时必须仍然开麦，否则房间会在机器人这里彻底没声。"""
    engine = _build_engine(ready=False)

    await engine.manager.play(PlaybackRequest.song("青花瓷", requester="小明"))

    assert engine.probe.waits == ["青花瓷"]
    assert engine.journal == ["mute", "ui:song", "restore"]


async def test_play_restores_the_microphone_when_the_ui_work_raises(initialized_test_singletons):
    """UI 层抛异常时也不能把机器人留在闭麦状态。"""

    class _ExplodingDriver(MusicUIDriverPort):
        def start_playback(self, request):
            raise RuntimeError("UI connection severed")

    engine = _build_engine(driver=_ExplodingDriver())

    with pytest.raises(RuntimeError, match="UI connection severed"):
        await engine.manager.play(PlaybackRequest.song("青花瓷", requester="小明"))

    assert engine.journal == ["mute", "restore"]


# ---------------------------------------------------------------------------
# Slice 4: 房间同步
# ---------------------------------------------------------------------------


async def test_play_adopts_the_room_topic_after_playback_is_confirmed(initialized_test_singletons):
    engine = _build_engine(
        driver=InMemoryMusicUIDriver(
            tracks={PlaybackMode.FAVORITES: PlaybackTrack("起风了", "买辣椒也用券", "起风了")}
        )
    )

    await engine.manager.play(
        PlaybackRequest(mode=PlaybackMode.FAVORITES, requester="小明", room_title="O Station")
    )

    assert engine.room_profile.topics == ["起风了"]


async def test_play_prefers_the_topic_observed_in_the_ui_over_the_derived_one(
    initialized_test_singletons,
):
    """专辑模式下房间话题是专辑名（见 AlbumCommand），不是队列第一行 —— 只有 UI 读得到。"""
    engine = _build_engine(
        driver=InMemoryMusicUIDriver(
            tracks={PlaybackMode.ALBUM: PlaybackTrack("倔强", "五月天", "神的孩子都在跳舞")},
            topics={PlaybackMode.ALBUM: "神的孩子都在跳舞"},
        )
    )

    await engine.manager.play(
        PlaybackRequest(mode=PlaybackMode.ALBUM, query="五月天", requester="小明")
    )

    # 若引擎忽略了 UI 读到的值而回落到队列行，这里会是 "倔强"。
    assert engine.room_profile.topics == ["神的孩子都在跳舞"]


async def test_play_records_player_playlist_and_title_after_playback_is_confirmed(
    initialized_test_singletons,
):
    engine = _build_engine(
        driver=InMemoryMusicUIDriver(
            playlists={PlaybackMode.PLAYLIST: "轻音乐 · 治愈白噪音"},
        )
    )

    await engine.manager.play(
        PlaybackRequest(
            mode=PlaybackMode.PLAYLIST,
            query="轻音乐",
            requester="小明",
            room_title="O Playlist",
        )
    )

    assert engine.info.player_name == "小明"
    assert engine.info.current_playlist_name == "轻音乐 · 治愈白噪音"
    assert engine.room_profile.titles == ["O Playlist"]


async def test_play_does_not_adopt_room_context_when_the_ui_fails(initialized_test_singletons):
    engine = _build_engine(
        driver=InMemoryMusicUIDriver(failures={PlaybackMode.ALBUM: "未找到相关专辑"})
    )

    await engine.manager.play(
        PlaybackRequest(mode=PlaybackMode.ALBUM, query="五月天", requester="小明")
    )

    assert engine.room_profile.topics == []
    assert engine.room_profile.titles == []
    assert engine.info.player_name is None


async def test_play_reports_a_started_song_when_only_the_room_sync_fails(
    initialized_test_singletons,
):
    """歌已经在响时，回复必须是歌 —— 房间同步失败只该进日志。"""
    engine = _build_engine()

    def _boom(_topic):
        return {"error": "Failed to change topic"}

    engine.room_profile.set_topic = _boom

    result = await engine.manager.play(PlaybackRequest.song("青花瓷", requester="小明"))

    assert result.started
    assert result.track.song == "青花瓷"
    assert result.as_response() == {
        "song": "青花瓷",
        "singer": "song-歌手",
        "album": "",
    }