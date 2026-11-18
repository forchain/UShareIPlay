"""Use-case tests for modules.playback.use_cases (PlaySong, SkipSong, PlayNext, PlaybackMuting)."""

from typing import Optional

import pytest

from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver
from ushareiplay.modules.mic.ports import MicControl
from ushareiplay.modules.playback.domain import (
    ACCOMPANIMENT_INVALID_PARAMETER_ERROR,
    NO_PLAYING_MUSIC_ERROR,
    PLAY_MODE_INVALID_PARAMETER_ERROR,
    PlaybackMode,
    PlaybackOutcome,
    PlaybackRequest,
    PlaybackStatus,
    PlaybackTrack,
    PlaybackVariant,
)
from ushareiplay.modules.playback.ports import (
    MediaSessionPort,
    NextTrackPort,
    RoomProfileWriter,
)
from ushareiplay.modules.playback.use_cases import (
    AdjustVolume,
    PauseResume,
    PlayNext,
    PlaySong,
    PlaybackMuting,
    PlaylistSession,
    QueryLyrics,
    SetAccompaniment,
    SetPlayMode,
    SkipSong,
)
from ushareiplay.modules.shared.config import ConfigView


class FakeMic(MicControl):
    def __init__(self, active: Optional[bool] = True):
        self.active = active
        self.calls: list[tuple] = []

    def state(self, *, wait: bool = False) -> Optional[bool]:
        self.calls.append(("state", wait))
        return self.active

    def set_active(self, enable: bool, *, report_noop: bool = False) -> dict:
        self.calls.append(("set_active", enable))
        self.active = enable
        return {"state": "1" if enable else "0"}

    def ensure_active(self) -> dict:
        self.calls.append(("ensure_active",))
        self.active = True
        return {"state": "1"}


class FakeMediaSession(MediaSessionPort):
    def __init__(self, ready: bool = True):
        self.ready = ready
        self.calls: list[tuple] = []

    def get_playback_info(self) -> dict:
        return {"song": "晴天", "singer": "周杰伦", "album": "叶惠美", "state": "Playing"}

    def wait_for_playback_ready(
        self,
        expected_song: Optional[str] = None,
        timeout: float = 5.0,
        settling_delay: float = 0.3,
    ) -> bool:
        self.calls.append(("wait_for_playback_ready", expected_song, timeout, settling_delay))
        return self.ready

    def skip_song(self) -> dict:
        self.calls.append(("skip_song",))
        return {"song": "旧歌", "singer": "歌手"}


class FakeNextTrack(NextTrackPort):
    def __init__(self, error: Optional[str] = None):
        self.error = error
        self.queries: list[str] = []

    def play_next(self, query: str) -> dict:
        self.queries.append(query)
        if self.error:
            return {"error": self.error}
        return {"song": query, "singer": "歌手", "album": "专辑"}


class FakeRoomProfile(RoomProfileWriter):
    def __init__(self, title_error: Optional[str] = None):
        self.title_error = title_error
        self.titles: list[str] = []
        self.topics: list[str] = []

    def set_title(self, title: str, theme: Optional[str] = None, requester: Optional[str] = None) -> dict:
        if self.title_error:
            return {"error": self.title_error}
        self.titles.append(title)
        return {"title": title}

    def set_topic(self, topic: str, requester: Optional[str] = None) -> dict:
        self.topics.append(topic)
        return {"topic": topic}


def _build_stack(
    *,
    online_users=None,
    mic_active: Optional[bool] = True,
    config_data=None,
    driver=None,
):
    online = set(online_users or ())
    config = ConfigView(
        config_data
        or {
            "room_owner": "BotOwner",
            "playback_mute": {
                "enabled": True,
                "guest_room_only": False,
                "auto_enable_on_mic": True,
                "timeout": 4.0,
                "settling_delay": 0.1,
            },
        }
    )
    mic = FakeMic(active=mic_active)
    media = FakeMediaSession()
    room_profile = FakeRoomProfile()
    playlist = PlaylistSession(
        config=config,
        room_profile=room_profile,
        online_users=lambda: online,
        avatar_usernames=lambda name: _async_set(name),
    )
    muting = PlaybackMuting(
        mic=mic,
        media_session=media,
        config=config,
        is_guest_room=lambda: False,
    )
    ui_driver = driver or InMemoryMusicUIDriver()
    play_song = PlaySong(ui_driver=ui_driver, playlist_session=playlist, playback_muting=muting)
    skip_song = SkipSong(media_session=media, playlist_session=playlist, playback_muting=muting)
    return play_song, skip_song, playlist, muting, mic, media, room_profile, ui_driver


async def _async_set(name: str) -> set[str]:
    return {name}


@pytest.mark.asyncio
async def test_rejected_play_never_mutes_mic_or_drives_ui():
    play_song, _, playlist, _, mic, media, _, ui_driver = _build_stack(online_users={"Alice"})
    playlist.player_name = "Alice"

    result = await play_song.execute(
        PlaybackRequest(mode=PlaybackMode.PLAYLIST, query="热歌榜", requester="Bob")
    )

    assert result.status is PlaybackStatus.REJECTED
    assert result.error == "Alice 正在播放歌单，请等待"
    assert mic.calls == []
    assert media.calls == []
    assert ui_driver.requests == []


@pytest.mark.asyncio
async def test_rejected_skip_never_mutes_mic_or_skips():
    _, skip_song, playlist, _, mic, media, _, _ = _build_stack(online_users={"Alice"})
    playlist.player_name = "Alice"

    result = await skip_song.execute("Bob")

    assert result == {"error": "Alice 正在播放歌单，请等待"}
    assert mic.calls == []
    assert media.calls == []


@pytest.mark.asyncio
async def test_allowed_play_follows_guard_mute_drive_adopt_and_restores_mic():
    play_song, _, playlist, _, mic, media, room_profile, _ = _build_stack()
    playlist.record_next("Charlie")

    result = await play_song.execute(
        PlaybackRequest(
            mode=PlaybackMode.PLAYLIST,
            query="流行热歌",
            requester="Alice",
            room_title="O Station",
        )
    )

    assert result.status is PlaybackStatus.STARTED
    assert playlist.player_name == "Alice"
    assert playlist.list_mode == "playlist"
    assert playlist.pending_next_count == 0
    assert mic.calls == [("state", False), ("set_active", False), ("ensure_active",)]
    assert media.calls == [("wait_for_playback_ready", None, 4.0, 0.1)]
    assert room_profile.titles == ["O Station"]


@pytest.mark.asyncio
async def test_failed_playback_short_circuits_readiness_wait_and_restores_mic():
    class FailingDriver(InMemoryMusicUIDriver):
        def start_playback(self, request: PlaybackRequest) -> PlaybackOutcome:
            return PlaybackOutcome.failed("未找到歌曲")

    play_song, _, _, _, mic, media, _, _ = _build_stack(driver=FailingDriver())
    result = await play_song.execute(PlaybackRequest.song("不存在的歌", requester="Alice"))

    assert result.status is PlaybackStatus.FAILED
    assert result.error == "未找到歌曲"
    assert media.calls == []
    assert mic.calls == [("state", False), ("set_active", False), ("ensure_active",)]


@pytest.mark.asyncio
async def test_allowed_skip_mutes_skips_waits_and_restores_mic():
    _, skip_song, _, _, mic, media, _, _ = _build_stack()

    result = await skip_song.execute("Alice")

    assert result == {"song": "旧歌", "singer": "歌手"}
    assert mic.calls == [("state", False), ("set_active", False), ("ensure_active",)]
    assert media.calls == [
        ("skip_song",),
        ("wait_for_playback_ready", None, 4.0, 0.1),
    ]


@pytest.mark.asyncio
async def test_play_next_records_next_queue_only_on_success():
    _, _, playlist, _, _, _, _, _ = _build_stack()
    next_driver = FakeNextTrack()
    play_next = PlayNext(next_driver=next_driver, playlist_session=playlist)

    ok_result = play_next.execute("Alice", "晴天")
    assert ok_result["song"] == "晴天"
    assert playlist.pending_next_count == 1
    assert playlist.next_queue_contributors == {"Alice"}

    failing_next = PlayNext(next_driver=FakeNextTrack(error="未找到"), playlist_session=playlist)
    err_result = failing_next.execute("Bob", "不存在")
    assert err_result == {"error": "未找到"}
    assert playlist.pending_next_count == 1
    assert playlist.next_queue_contributors == {"Alice"}


@pytest.mark.asyncio
async def test_set_play_mode_use_case_validates_caches_and_switches():
    driver = InMemoryMusicUIDriver(play_mode="list")
    cache = {"key": "list"}
    notes = []
    use_case = SetPlayMode(
        ui_driver=driver,
        get_play_mode_key=lambda: cache["key"],
        note_play_mode=lambda key, reason: (cache.__setitem__("key", key), notes.append((key, reason))),
    )

    # Invalid parameter
    assert await use_case.execute("bogus") == {"error": PLAY_MODE_INVALID_PARAMETER_ERROR}
    assert await use_case.execute(True) == {"error": PLAY_MODE_INVALID_PARAMETER_ERROR}

    # Already target in cache -> no UI call
    assert await use_case.execute(0) == {
        "success": True,
        "mode": "顺序播放",
        "message": "已经是顺序播放模式",
    }
    assert driver.play_mode_requests == []

    # Switch to random (-1)
    assert await use_case.execute(-1) == {
        "success": True,
        "mode": "随机播放",
        "message": "成功切换到随机播放模式",
    }
    assert driver.play_mode_requests == ["random"]
    assert cache["key"] == "random"
    assert notes == [("random", "mode_ui_detect")]

    # No music playing
    driver_no_music = InMemoryMusicUIDriver(no_music=True)
    uc_no_music = SetPlayMode(ui_driver=driver_no_music)
    assert await uc_no_music.execute(1) == {"error": NO_PLAYING_MUSIC_ERROR}


@pytest.mark.asyncio
async def test_set_accompaniment_use_case_validates_and_toggles():
    driver = InMemoryMusicUIDriver(accompaniment=False)
    use_case = SetAccompaniment(ui_driver=driver)

    assert await use_case.execute("invalid") == {"error": ACCOMPANIMENT_INVALID_PARAMETER_ERROR}
    assert await use_case.execute(1) == {"enabled": "on"}
    assert driver.accompaniment is True
    assert driver.accompaniment_clicks == 1
    assert await use_case.execute("0") == {"enabled": "off"}
    assert driver.accompaniment is False
    assert driver.accompaniment_clicks == 2


def test_query_lyrics_use_case_explicit_and_current_song_fallback():
    driver = InMemoryMusicUIDriver(
        lyrics={
            "夜曲 周杰伦": "一群嗜血的蚂蚁",
            "晴天 周杰伦 叶惠美": "故事的小黄花",
        },
        playback_info={"song": "晴天", "singer": "周杰伦", "album": "叶惠美", "state": "Playing"},
    )
    use_case = QueryLyrics(ui_driver=driver, media_session=driver)

    assert use_case.execute("夜曲 周杰伦") == {"lyrics": "一群嗜血的蚂蚁"}
    assert use_case.execute("") == {"lyrics": "故事的小黄花"}
    assert driver.lyrics_requests == ["夜曲 周杰伦", "晴天 周杰伦 叶惠美"]

    driver_no_music = InMemoryMusicUIDriver(no_music=True)
    uc_no_music = QueryLyrics(ui_driver=driver_no_music, media_session=driver_no_music)
    assert uc_no_music.execute("") == {"error": "Failed to get playback info"}


@pytest.mark.asyncio
async def test_pause_resume_use_case_respects_guard_and_toggles_mic():
    _, _, playlist, _, mic, _, _, _ = _build_stack(online_users={"Alice"}, mic_active=True)
    driver = InMemoryMusicUIDriver(
        playback_info={"song": "晴天", "singer": "周杰伦", "album": "叶惠美", "state": "Playing"}
    )
    use_case = PauseResume(
        media_session=driver,
        playback_control=driver,
        playlist_session=playlist,
        mic=mic,
    )

    # Guard rejects Bob when Alice is playing a playlist
    playlist.player_name = "Alice"
    assert await use_case.execute("Bob", 1) == {"error": "Alice 正在播放歌单，请等待"}
    assert driver.pause_calls == []
    assert mic.calls == []

    # Invalid parameter
    assert await use_case.execute("Alice", 2) == {"error": "Invalid parameter, must be 0 or 1"}

    # Pause (1) while Playing -> turns off mic then pauses
    res_pause = await use_case.execute("Alice", 1)
    assert res_pause == {"song": "晴天", "singer": "周杰伦", "action": "Paused"}
    assert driver.pause_calls == [True]
    assert mic.calls == [("set_active", False)]

    # Pause (1) while already Paused -> no-op
    res_already = await use_case.execute("Alice", 1)
    assert res_already == {"song": "晴天", "singer": "周杰伦", "action": "Paused"}
    assert driver.pause_calls == [True]

    # Toggle (None) while Paused -> resumes then turns on mic
    res_resume = await use_case.execute("Alice", None)
    assert res_resume == {"song": "晴天", "singer": "周杰伦", "action": "Resumed"}
    assert driver.pause_calls == [True, False]
    assert mic.calls == [("set_active", False), ("set_active", True)]


def test_adjust_volume_use_case_reads_validates_and_steps():
    driver = InMemoryMusicUIDriver(volume=5)
    use_case = AdjustVolume(playback_control=driver)

    assert use_case.execute(None) == {"volume": 5, "current": True}
    assert use_case.execute(-1) == {"error": "Invalid target volume: -1. Must be integer between 0-15"}
    assert use_case.execute(16) == {"error": "Invalid target volume: 16. Must be integer between 0-15"}
    assert use_case.execute(True) == {"error": "Invalid target volume: True. Must be integer between 0-15"}

    assert use_case.execute(5) == {"volume": 5}
    assert driver.volume_steps == []

    assert use_case.execute(8) == {"volume": 8, "delta": 3}
    assert driver.volume_steps == [3]

    driver_unavailable = InMemoryMusicUIDriver(volume_unavailable=True)
    uc_unavail = AdjustVolume(playback_control=driver_unavailable)
    assert uc_unavail.execute(None) == {"error": "Failed to get current volume level"}
    assert uc_unavail.execute(8) == {"error": "Failed to get current volume level"}
