"""Use-case tests for modules.playback.use_cases (PlaySong, SkipSong, PlayNext, PlaybackMuting)."""

from typing import Optional

import pytest

from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver
from ushareiplay.modules.mic.ports import MicControl
from ushareiplay.modules.playback.domain import (
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
    PlayNext,
    PlaySong,
    PlaybackMuting,
    PlaylistSession,
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
