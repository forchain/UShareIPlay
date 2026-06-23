from types import SimpleNamespace

import pytest

from ushareiplay.commands.info import InfoCommand
from ushareiplay.managers.info_manager import InfoManager


@pytest.fixture
def info_manager():
    if hasattr(InfoManager, "_instance"):
        del InfoManager._instance
    manager = InfoManager.instance()
    manager._logger = SimpleNamespace(info=lambda _message: None)
    return manager


class _MusicHandler:
    play_mode_key = "unknown"

    def play_mode_key_to_name(self, _key):
        return "未知"


def _patch_common_info_dependencies(monkeypatch, info_manager):
    monkeypatch.setattr(
        "ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance",
        lambda: _MusicHandler(),
    )
    info_manager._online_users = set()
    info_manager._party_manager = SimpleNamespace(init_time=None)


@pytest.mark.asyncio
async def test_info_command_returns_empty_release_date_when_cache_missing(monkeypatch, info_manager):
    _patch_common_info_dependencies(monkeypatch, info_manager)
    command = InfoCommand(
        SimpleNamespace(soul_handler=SimpleNamespace(), music_handler=SimpleNamespace())
    )

    result = await command.process(SimpleNamespace(nickname="Console"), [])

    assert result["release_date"] == ""


@pytest.mark.asyncio
async def test_info_command_preserves_cached_release_date(monkeypatch, info_manager):
    _patch_common_info_dependencies(monkeypatch, info_manager)
    info_manager._playback_info_cache = {
        "song": "泼墨桃花",
        "singer": "林峯",
        "album": "爱在记忆中找你",
        "release_date": "2007-11-23",
    }
    command = InfoCommand(
        SimpleNamespace(soul_handler=SimpleNamespace(), music_handler=SimpleNamespace())
    )

    result = await command.process(SimpleNamespace(nickname="Console"), [])

    assert result["release_date"] == "2007-11-23"
