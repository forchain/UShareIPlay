"""SkipCommand / PauseCommand 的歌单守护门禁。

守护在命令层只做一件事：先问 `guard_switch`，被拦就返回错误 dict，
不碰播放器、不暂停/恢复，也不动麦克风。
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import ushareiplay.commands.pause as pause_module
import ushareiplay.commands.skip as skip_module
from ushareiplay.commands.pause import PauseCommand
from ushareiplay.commands.skip import SkipCommand
from ushareiplay.models.message_info import MessageInfo


def _make_controller():
    controller = MagicMock()
    controller.soul_handler = MagicMock()
    controller.music_handler = MagicMock()
    return controller


def _guard_error():
    return {"error": "不约儿童 正在播放歌单，请等待"}


def _fake_music(monkeypatch, module):
    music = MagicMock()
    music.skip_song.return_value = {"song": "晴天", "singer": "周杰伦"}
    music.get_playback_info.return_value = {
        "state": "Playing",
        "song": "晴天",
        "singer": "周杰伦",
    }
    music.pause_resume.return_value = {}
    monkeypatch.setattr(module.MusicManager, "instance", lambda: music)
    return music


class _FakeMuting:
    """Counts entries into the PlaybackMuting guard without touching a mic."""

    def __init__(self):
        self.entries = 0

    @contextmanager
    def guard(self):
        self.entries += 1
        yield False


@pytest.fixture
def muting(monkeypatch):
    fake = _FakeMuting()
    monkeypatch.setattr(
        skip_module.PlaybackMuting, "instance", staticmethod(lambda: fake)
    )
    return fake


@pytest.fixture
def skip_command():
    command = SkipCommand(_make_controller())
    command._playlist_adoption = MagicMock()
    command._playlist_adoption.guard_switch = AsyncMock(return_value=None)
    return command


@pytest.fixture
def pause_command():
    command = PauseCommand(_make_controller())
    command._playlist_adoption = MagicMock()
    command._playlist_adoption.guard_switch = AsyncMock(return_value=None)
    command._mic_manager = MagicMock()
    command._mic_manager.set_active.return_value = {}
    return command


@pytest.mark.asyncio
async def test_skip_blocked_by_guard_never_touches_the_player(
    skip_command, muting, monkeypatch
):
    music = _fake_music(monkeypatch, skip_module)
    skip_command._playlist_adoption.guard_switch.return_value = _guard_error()

    result = await skip_command.do_process(
        MessageInfo(content="/skip", nickname="房客"), []
    )

    assert result == _guard_error()
    skip_command._playlist_adoption.guard_switch.assert_awaited_once_with("房客")
    assert muting.entries == 0
    music.skip_song.assert_not_called()


@pytest.mark.asyncio
async def test_skip_allowed_by_guard_reaches_the_player(
    skip_command, muting, monkeypatch
):
    music = _fake_music(monkeypatch, skip_module)

    result = await skip_command.do_process(
        MessageInfo(content="/skip", nickname="房客"), []
    )

    assert result == {"song": "晴天", "singer": "周杰伦"}
    skip_command._playlist_adoption.guard_switch.assert_awaited_once_with("房客")
    assert muting.entries == 1
    music.skip_song.assert_called_once_with()


@pytest.mark.asyncio
async def test_pause_blocked_by_guard_never_pauses_or_touches_the_mic(
    pause_command, monkeypatch
):
    music = _fake_music(monkeypatch, pause_module)
    pause_command._playlist_adoption.guard_switch.return_value = _guard_error()

    result = await pause_command.do_process(
        MessageInfo(content="/pause 1", nickname="房客"), ["1"]
    )

    assert result == _guard_error()
    pause_command._playlist_adoption.guard_switch.assert_awaited_once_with("房客")
    music.get_playback_info.assert_not_called()
    music.pause_resume.assert_not_called()
    pause_command._mic_manager.set_active.assert_not_called()


@pytest.mark.asyncio
async def test_pause_allowed_by_guard_pauses_and_turns_off_the_mic(
    pause_command, monkeypatch
):
    music = _fake_music(monkeypatch, pause_module)

    result = await pause_command.do_process(
        MessageInfo(content="/pause 1", nickname="房客"), ["1"]
    )

    assert pause_command._playlist_adoption.guard_switch.await_args.args == ("房客",)
    assert result["action"] == "Paused"
    music.pause_resume.assert_called_once_with(True)
    pause_command._mic_manager.set_active.assert_called_once_with(False)
