"""SkipCommand / PauseCommand 的歌单守护门禁。

守护在命令层只做一件事：委托给 `SkipSong` / `PauseResume` 用例，
被拦就返回错误 dict，不碰播放器、不暂停/恢复，也不动麦克风。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver
from ushareiplay.adapters.inbound.chat.pause import PauseCommand
from ushareiplay.adapters.inbound.chat.skip import SkipCommand
from ushareiplay.modules.shared.message_info import MessageInfo
from ushareiplay.modules.playback.use_cases import PauseResume


def _make_controller():
    controller = MagicMock()
    controller.soul_handler = MagicMock()
    controller.music_handler = MagicMock()
    return controller


def _guard_error():
    return {"error": "不约儿童 正在播放歌单，请等待"}


@pytest.fixture
def skip_command():
    return SkipCommand(_make_controller())


@pytest.fixture
def pause_command():
    return PauseCommand(_make_controller())


@pytest.mark.asyncio
async def test_skip_command_delegates_guard_and_mute_to_the_engine(skip_command):
    """SkipCommand 不再自己守护/闭麦：整条流水线归 `SkipSong` 用例。"""
    skip_command.controller.skip_song.execute = AsyncMock(
        return_value={"song": "晴天", "singer": "周杰伦"}
    )

    result = await skip_command.do_process(
        MessageInfo(content="/skip", nickname="房客"), []
    )

    assert result == {"song": "晴天", "singer": "周杰伦"}
    skip_command.controller.skip_song.execute.assert_awaited_once_with("房客")


@pytest.mark.asyncio
async def test_pause_command_delegates_to_pause_resume_use_case(pause_command):
    pause_command.controller.pause_resume.execute = AsyncMock(
        return_value={"song": "晴天", "singer": "周杰伦", "action": "Paused"}
    )

    result = await pause_command.do_process(
        MessageInfo(content="/pause 1", nickname="房客"), ["1"]
    )

    assert result == {"song": "晴天", "singer": "周杰伦", "action": "Paused"}
    pause_command.controller.pause_resume.execute.assert_awaited_once_with("房客", 1)


@pytest.mark.asyncio
async def test_pause_blocked_by_guard_never_pauses_or_touches_the_mic():
    driver = InMemoryMusicUIDriver()
    mic = MagicMock()
    playlist_session = SimpleNamespace(guard_switch=AsyncMock(return_value=_guard_error()))
    use_case = PauseResume(
        media_session=driver,
        playback_control=driver,
        playlist_session=playlist_session,
        mic=mic,
    )

    result = await use_case.execute("房客", 1)

    assert result == _guard_error()
    playlist_session.guard_switch.assert_awaited_once_with("房客")
    assert driver.pause_calls == []
    mic.set_active.assert_not_called()


@pytest.mark.asyncio
async def test_pause_allowed_by_guard_pauses_and_turns_off_the_mic():
    driver = InMemoryMusicUIDriver(
        playback_info={"song": "晴天", "singer": "周杰伦", "state": "Playing"}
    )
    mic = MagicMock()
    mic.set_active.return_value = {}
    playlist_session = SimpleNamespace(guard_switch=AsyncMock(return_value=None))
    use_case = PauseResume(
        media_session=driver,
        playback_control=driver,
        playlist_session=playlist_session,
        mic=mic,
    )

    result = await use_case.execute("房客", 1)

    assert playlist_session.guard_switch.await_args.args == ("房客",)
    assert result["action"] == "Paused"
    assert driver.pause_calls == [True]
    mic.set_active.assert_called_once_with(False)
