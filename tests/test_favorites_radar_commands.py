"""#425：`:fav` 与 `:play ""`/`:play ?` 迁到播放引擎后的命令层测试。

测试面是三个命令的公开入口（`FavCommand.do_process` / `PlayCommand.do_process`）与
它们的返回字典。底下是真的 `MusicManager.play()` 流水线 —— 守护、静音、房间同步、
`as_response()` 全部走生产代码，只有 Appium UI 与 MediaSession 被内存替身顶掉。

因此「`:fav type 粤语` 房间里叫「粤音」」「模板渲染不出 KeyError」「守护拒绝时一个
UI 动作都不发生」考的是真实路径，而不是某个替身的自我陈述。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from pathlib import Path

from ushareiplay.commands.fav import FavCommand
from ushareiplay.commands.play import PlayCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.models import (
    PlaybackMode,
    PlaybackRequest,
    PlaybackVariant,
)
from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.managers.playlist_adoption import PlaylistAdoption
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver

QUEUE_TEXT = "喜帖街 - 谢安琪\n富士山下 - 陈奕迅"


class _InfoManager:
    """InfoManager 替身：歌单守护判定 + 房间播放者状态。"""

    def __init__(self, protection_error=None):
        self.protection_error = protection_error
        self.player_name = None
        self.current_playlist_name = None

    async def check_playlist_protection(self, requester, config=None):
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


class _MicManager:
    """记录真实开闭麦动作。守护拒绝时这个列表必须是空的。"""

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


class _Controller:
    """BaseCommand 构造所需的最小 controller。"""

    def __init__(self):
        self.soul_handler = SimpleNamespace(log_error=lambda *_a, **_k: None)
        self.music_handler = SimpleNamespace()


def _wire_engine(*, driver=None, protection_error=None):
    """装配真引擎：只有 UI 端口、MediaSession 与麦克风是替身。"""
    journal = []
    driver = driver or InMemoryMusicUIDriver(
        playlists={PlaybackMode.FAVORITES: QUEUE_TEXT},
        journal=journal,
    )

    adoption = PlaylistAdoption.instance()
    adoption._info = _InfoManager(protection_error=protection_error)
    adoption._room_profile = _RoomProfileManager()
    adoption._music = SimpleNamespace(list_mode=None, no_skip=0)

    MusicManager.initialize(ui_driver=driver)
    PlaybackMuting.initialize(
        SimpleNamespace(logger=MagicMock(), config={}),
        SimpleNamespace(wait_for_playback_ready=lambda **_k: True),
        _MicManager(journal),
    )
    return SimpleNamespace(
        manager=MusicManager.instance(),
        driver=driver,
        info=adoption._info,
        room_profile=adoption._room_profile,
        journal=journal,
    )


def _message(nickname="小明"):
    return SimpleNamespace(nickname=nickname)


def _response_template(prefix):
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8")
    )
    return {item["prefix"]: item for item in config["commands"]}[prefix]["response_template"]


def _render(prefix, result):
    """照 `CommandManager` 的做法渲染公屏文案（发行日期由它兜底）。"""
    response = dict(result)
    response.setdefault("release_date", "")
    return _response_template(prefix).format(**response)


# ---------------------------------------------------------------------------
# Slice 1: 子命令怎么翻译成播放请求
# ---------------------------------------------------------------------------


async def test_bare_fav_asks_the_engine_for_every_favourite(initialized_test_singletons):
    engine = _wire_engine()

    await FavCommand(_Controller()).do_process(_message(), [])

    driven = engine.driver.requests[0]
    assert driven.mode is PlaybackMode.FAVORITES
    assert driven.variant is PlaybackVariant.ALL
    assert driven.query is None
    assert driven.requester == "小明"


@pytest.mark.parametrize("subcommand", ["0", "type"])
async def test_fav_type_asks_the_engine_for_the_filtered_list(
    subcommand, initialized_test_singletons
):
    engine = _wire_engine()

    await FavCommand(_Controller()).do_process(_message(), [subcommand, "粤", "语"])

    driven = engine.driver.requests[0]
    assert driven.variant is PlaybackVariant.FILTER
    # 关键字允许带空格，驱动拿到的是完整的一串
    assert driven.query == "粤 语"


@pytest.mark.parametrize("subcommand", ["2", "search"])
async def test_fav_search_asks_the_engine_for_the_matches_inside_favourites(
    subcommand, initialized_test_singletons
):
    engine = _wire_engine()

    await FavCommand(_Controller()).do_process(_message(), [subcommand, "谢安琪"])

    driven = engine.driver.requests[0]
    assert driven.variant is PlaybackVariant.SEARCH
    assert driven.query == "谢安琪"


async def test_fav_rejects_an_unknown_subcommand_without_touching_the_engine(
    initialized_test_singletons,
):
    engine = _wire_engine()

    result = await FavCommand(_Controller()).do_process(_message(), ["dance", "粤语"])

    assert "error" in result
    assert engine.driver.requests == []


async def test_fav_rejects_a_subcommand_without_its_keyword(initialized_test_singletons):
    engine = _wire_engine()

    result = await FavCommand(_Controller()).do_process(_message(), ["type"])

    assert "error" in result
    assert engine.driver.requests == []


async def test_play_with_an_empty_query_asks_the_engine_for_every_favourite(
    initialized_test_singletons,
):
    engine = _wire_engine()

    await PlayCommand(_Controller()).do_process(_message(), [])

    driven = engine.driver.requests[0]
    assert driven.mode is PlaybackMode.FAVORITES
    assert driven.variant is PlaybackVariant.ALL


async def test_play_with_a_question_mark_asks_the_engine_for_radar(
    initialized_test_singletons,
):
    engine = _wire_engine()

    await PlayCommand(_Controller()).do_process(_message(), ["?"])

    driven = engine.driver.requests[0]
    assert driven.mode is PlaybackMode.RADAR
    assert driven.requester == "小明"


# ---------------------------------------------------------------------------
# Slice 2: 命令不再自己动手 —— 房间同步全部来自引擎流水线
# ---------------------------------------------------------------------------


async def test_fav_adopts_the_requester_the_room_title_and_the_playlist(initialized_test_singletons):
    engine = _wire_engine(
        driver=InMemoryMusicUIDriver(
            titles={PlaybackMode.FAVORITES: "粤音"},
            topics={PlaybackMode.FAVORITES: "喜帖街 - 谢安琪"},
            playlists={PlaybackMode.FAVORITES: QUEUE_TEXT},
        )
    )

    await FavCommand(_Controller()).do_process(_message("阿花"), ["type", "粤语"])

    assert engine.info.player_name == "阿花"
    assert engine.room_profile.titles == ["粤音"]
    assert engine.room_profile.topics == ["喜帖街"]


async def test_radar_adopts_the_radio_title_and_the_current_program(initialized_test_singletons):
    engine = _wire_engine(
        driver=InMemoryMusicUIDriver(
            tracks={PlaybackMode.RADAR: _radar_track()},
            titles={PlaybackMode.RADAR: "O Radio"},
            topics={PlaybackMode.RADAR: "雷达电台"},
        )
    )

    await PlayCommand(_Controller()).do_process(_message(), ["?"])

    assert engine.room_profile.titles == ["O Radio"]
    assert engine.room_profile.topics == ["雷达电台"]


def _radar_track():
    from ushareiplay.managers.playback.models import PlaybackTrack

    return PlaybackTrack(song="雷达电台", singer="O Radio")


# ---------------------------------------------------------------------------
# Slice 3: 回复 —— 六个模板都要渲染得出来
# ---------------------------------------------------------------------------


async def test_fav_reply_renders_the_queue_listing_into_the_playlist_template(
    initialized_test_singletons,
):
    _wire_engine()

    result = await FavCommand(_Controller()).do_process(_message(), [])

    assert _render("fav", result) == QUEUE_TEXT


async def test_play_empty_reply_still_renders_song_and_singer(initialized_test_singletons):
    _wire_engine()

    result = await PlayCommand(_Controller()).do_process(_message(), [])

    assert _render("play", result) == "favorites - favorites-歌手 •  • "


async def test_play_radar_reply_still_renders_song_and_singer(initialized_test_singletons):
    _wire_engine(driver=InMemoryMusicUIDriver(tracks={PlaybackMode.RADAR: _radar_track()}))

    result = await PlayCommand(_Controller()).do_process(_message(), ["?"])

    assert _render("play", result) == "雷达电台 - O Radio •  • "


@pytest.mark.parametrize("prefix", ["play", "fav", "next", "singer", "playlist", "radio", "album"])
def test_every_music_template_renders_against_a_started_reply(prefix):
    """五个纯 `{playlist}` 模板遇上缺键就是 `KeyError`，用户连报错都收不到。

    这里拿引擎的标准成功回复去渲染每个模板，断言没有一个模板需要命令层再手拼键。
    """
    from ushareiplay.managers.playback.models import PlaybackResult, PlaybackStatus

    result = PlaybackResult(
        status=PlaybackStatus.STARTED,
        track=_radar_track(),
        playlist=QUEUE_TEXT,
    )
    response = result.as_response()
    response.setdefault("release_date", "")

    assert isinstance(_response_template(prefix).format(**response), str)


# ---------------------------------------------------------------------------
# Slice 4: 歌曲守护
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_factory",
    [
        lambda: PlaybackRequest.favorites(requester="小明"),
        lambda: PlaybackRequest.favorites("粤语", variant=PlaybackVariant.FILTER),
        lambda: PlaybackRequest.favorites("谢安琪", variant=PlaybackVariant.SEARCH),
        lambda: PlaybackRequest.radar(requester="小明"),
    ],
)
async def test_a_protected_room_rejects_every_favourites_and_radar_shape_without_touching_anything(
    request_factory, initialized_test_singletons
):
    engine = _wire_engine(protection_error={"error": "小红 正在播放歌单，请等待"})

    result = await engine.manager.play(request_factory())

    assert result.rejected
    assert result.as_response() == {"error": "小红 正在播放歌单，请等待"}
    # 一个 UI 动作都不该发生，麦克风也不该被动过
    assert engine.driver.requests == []
    assert engine.journal == []


# ---------------------------------------------------------------------------
# Slice 5: 静音生命周期交给引擎
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command_class", [PlayCommand, FavCommand])
def test_migrated_commands_no_longer_ask_for_command_level_muting(command_class):
    """命令级闭麦发生在守护之前，被拒绝的切歌也会响一次无来由的静音。

    迁到引擎后由 `MusicManager.play()` 在守护通过后自己闭麦（ADR-0007），命令层再
    声明一次只会把静音包两遍。
    """
    assert command_class.playback_muting is False


async def test_fav_reports_the_guard_message_when_someone_else_is_playing(
    initialized_test_singletons,
):
    _wire_engine(protection_error={"error": "小红 正在播放歌单，请等待"})

    result = await FavCommand(_Controller()).do_process(_message(), [])

    assert result == {"error": "小红 正在播放歌单，请等待"}


async def test_play_empty_reports_the_guard_message_when_someone_else_is_playing(
    initialized_test_singletons,
):
    _wire_engine(protection_error={"error": "小红 正在播放歌单，请等待"})

    result = await PlayCommand(_Controller()).do_process(_message(), [])

    assert result == {"error": "小红 正在播放歌单，请等待"}


async def test_play_radar_reports_the_guard_message_when_someone_else_is_playing(
    initialized_test_singletons,
):
    _wire_engine(protection_error={"error": "小红 正在播放歌单，请等待"})

    result = await PlayCommand(_Controller()).do_process(_message(), ["?"])

    assert result == {"error": "小红 正在播放歌单，请等待"}
