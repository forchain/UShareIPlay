"""单曲点播是插播，不是换歌单 —— 房间的歌单上下文不该被改写。

线上回归（2026-10-21 16:11，控制台记录）：

    [电台] 猜你喜欢-沉浸刷歌 (by Timer)   <- 定时器开的电台在放
    :play 爱情男女                        <- Joyer 在电台里点了一首歌
    [song] 猜你喜欢-沉浸刷歌 (by Joyer)   <- 房间歌单变成「歌曲」，还换了主人
    ...（跳过这首之后 QQ 音乐接着放电台，16:13 那首仍是电台推的歌）

根因在 `PlaylistAdoption.adopt()`：它对**每一种**播放模式都写 `player_name` 与
`list_mode`，于是单曲点播把正在放的电台改写成「点播者的歌曲」。#421 把 `:play
<歌名>` 迁进统一引擎时就是这样接的线，迁移前 `play_song()` 根本不碰歌单上下文。

这条回归钉住用户看到的那一行：电台在放时点一首歌，`/info` 的歌单类型、歌单名
与播放者都不变。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.commands.play import PlayCommand
from ushareiplay.handlers.qq_music_handler import QQMusicHandler
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.managers.playlist_adoption import PlaylistAdoption
from ushareiplay.state.playlist_state import PlaylistState
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver

RADIO_NAME = "猜你喜欢-沉浸刷歌"


class _RoomProfile:
    """房名/话题落地归 RoomProfileManager 与 Soul UI，这里只记录调用。"""

    def set_title(self, title):
        return None

    def set_topic(self, topic):
        return None


class _ReadinessProbe:
    def wait_for_playback_ready(self, expected_song=None, timeout=5.0, settling_delay=0.3):
        return True


class _MicManager:
    def state(self):
        return True

    def set_active(self, enable):
        return {"state": "1"}

    def ensure_active(self):
        return {"state": "1"}


def _play_command():
    return PlayCommand(SimpleNamespace(soul_handler=MagicMock(), music_handler=MagicMock()))


@pytest.mark.asyncio
async def test_radio_keeps_the_room_playlist_when_a_single_song_is_played(
    monkeypatch, initialized_test_singletons
):
    """电台在放时点一首歌：`/info` 的歌单行仍是电台与它的播放者。"""
    PlaylistState.initialize()
    info = InfoManager.initialize(SimpleNamespace(config={}, logger=MagicMock()))
    info.current_playlist_name = RADIO_NAME

    # `/info` 的歌单类型直接读 `QQMusicHandler.list_mode`；这里让替身与引擎同源。
    music = {"list_mode": "unknown"}

    class _MusicHandlerStub:
        @property
        def list_mode(self):
            return music["list_mode"]

        @list_mode.setter
        def list_mode(self, value):
            music["list_mode"] = value

    monkeypatch.setattr(
        QQMusicHandler, "instance", classmethod(lambda cls: _MusicHandlerStub())
    )

    adoption = PlaylistAdoption.instance()
    adoption._info = info
    adoption._room_profile = _RoomProfile()
    adoption._music = _MusicHandlerStub()

    MusicManager.initialize(ui_driver=InMemoryMusicUIDriver())
    PlaybackMuting.initialize(
        SimpleNamespace(logger=MagicMock(), config={}), _ReadinessProbe(), _MicManager()
    )

    # 定时器开的电台已经在放。
    assert adoption.adopt(
        "Timer", mode="radio", title=RADIO_NAME, topic=RADIO_NAME, playlist=RADIO_NAME
    ) is None
    before = info.get_playlist_info()
    assert before == {"type": "radio", "name": RADIO_NAME}
    assert info.player_name == "Timer"

    # Joyer 在电台里点一首歌。
    result = await _play_command().do_process(
        SimpleNamespace(nickname="Joyer"), ["爱情男女"]
    )
    assert result["song"], result

    playlist = info.get_playlist_info()
    rendered = f"[{playlist['type']}] {playlist['name']} (by {info.player_name})"
    assert rendered == f"[radio] {RADIO_NAME} (by Timer)", rendered
