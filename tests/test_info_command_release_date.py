from types import SimpleNamespace

import pytest

from ushareiplay.adapters.inbound.chat.info import InfoCommand
from ushareiplay.modules.room import InfoManager
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
from ushareiplay.managers.playlist_session import PlaylistSession
from tests.legacy_state import PresenceTracker
from tests.legacy_state import RoomState


@pytest.fixture
def info_manager():
    for cls in (
        PlaybackBroadcaster,
        PlaylistSession,
        PresenceTracker,
        RoomState,
    ):
        cls.reset_instance()
    broadcaster = PlaybackBroadcaster.initialize()
    playlist = PlaylistSession.initialize()
    presence = PresenceTracker.initialize()
    room_state = RoomState.initialize()
    return InfoManager(
        room_state=room_state,
        presence=presence,
        playlist=playlist,
        playback_cache=broadcaster,
        logger=SimpleNamespace(info=lambda _message: None),
    )


class _MusicHandler:
    play_mode_key = "unknown"

    def play_mode_key_to_name(self, _key):
        return "未知"


def _patch_common_info_dependencies(monkeypatch, info_manager):
    monkeypatch.setattr(
        "ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance",
        lambda: _MusicHandler(),
    )
    # 直接注入目标状态模块（见 ADR-0004）
    PresenceTracker.instance()._online_users = set()
    info_manager._party_manager = SimpleNamespace(init_time=None)


@pytest.mark.asyncio
async def test_info_command_returns_empty_release_date_when_cache_missing(monkeypatch, info_manager):
    _patch_common_info_dependencies(monkeypatch, info_manager)
    command = InfoCommand(
        SimpleNamespace(
            soul_handler=SimpleNamespace(),
            music_handler=SimpleNamespace(),
            info_manager=info_manager,
            timer_manager=SimpleNamespace(status_line=lambda: "定时器: 已停止，共 0 个"),
            room_profile_manager=SimpleNamespace(recommendation_enabled=None),
        )
    )

    result = await command.process(SimpleNamespace(nickname="Console"), [])

    assert result["release_date"] == ""


@pytest.mark.asyncio
async def test_info_command_preserves_cached_release_date(monkeypatch, info_manager):
    _patch_common_info_dependencies(monkeypatch, info_manager)
    PlaybackBroadcaster.instance()._playback_info_cache = {
        "song": "泼墨桃花",
        "singer": "林峯",
        "album": "爱在记忆中找你",
        "release_date": "2007-11-23",
    }
    command = InfoCommand(
        SimpleNamespace(
            soul_handler=SimpleNamespace(),
            music_handler=SimpleNamespace(),
            info_manager=info_manager,
            timer_manager=SimpleNamespace(status_line=lambda: "定时器: 已停止，共 0 个"),
            room_profile_manager=SimpleNamespace(recommendation_enabled=None),
        )
    )

    result = await command.process(SimpleNamespace(nickname="Console"), [])

    assert result["release_date"] == "2007-11-23"
