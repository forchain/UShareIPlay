from types import SimpleNamespace

import pytest

from ushareiplay.adapters.inbound.chat.info import InfoCommand
from ushareiplay.modules.room import InfoManager, PresenceTracker, RoomStateService
from ushareiplay.modules.playback.broadcaster import PlaybackBroadcaster
from ushareiplay.modules.playback.use_cases import PlaylistSession


@pytest.fixture
def info_manager():
    playlist = PlaylistSession()
    broadcaster = PlaybackBroadcaster(playlist_session=playlist)
    presence = PresenceTracker()
    room_state = RoomStateService()
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


def _patch_common_info_dependencies(info_manager):
    info_manager._presence._online_users = set()
    info_manager._party_manager = SimpleNamespace(init_time=None)


@pytest.mark.asyncio
async def test_info_command_returns_empty_release_date_when_cache_missing(info_manager):
    _patch_common_info_dependencies(info_manager)
    command = InfoCommand(
        SimpleNamespace(
            soul_handler=SimpleNamespace(),
            music_handler=_MusicHandler(),
            info_manager=info_manager,
            timer_manager=SimpleNamespace(status_line=lambda: "定时器: 已停止，共 0 个"),
            room_profile_manager=SimpleNamespace(recommendation_enabled=None),
        )
    )

    result = await command.process(SimpleNamespace(nickname="Console"), [])

    assert result["release_date"] == ""


@pytest.mark.asyncio
async def test_info_command_preserves_cached_release_date(info_manager):
    _patch_common_info_dependencies(info_manager)
    info_manager._playback_cache._playback_info_cache = {
        "song": "泼墨桃花",
        "singer": "林峯",
        "album": "爱在记忆中找你",
        "release_date": "2007-11-23",
    }
    command = InfoCommand(
        SimpleNamespace(
            soul_handler=SimpleNamespace(),
            music_handler=_MusicHandler(),
            info_manager=info_manager,
            timer_manager=SimpleNamespace(status_line=lambda: "定时器: 已停止，共 0 个"),
            room_profile_manager=SimpleNamespace(recommendation_enabled=None),
        )
    )

    result = await command.process(SimpleNamespace(nickname="Console"), [])

    assert result["release_date"] == "2007-11-23"
