"""生产 `QQMusicUIDriver` 的离线测试。

测试面只有端口方法 `QQMusicUIDriver.start_playback(request)`。QQMusicHandler 由测试
模块内的假替身提供 —— 替身只暴露驱动真正调用的那几个 UI 方法（查歌、点第一首、
播放页收藏），因此断言考的是「驱动怎么编排」而不是「Appium 点了哪个坐标」。

按 #421 的分工，本驱动只实现 `PlaybackMode.SONG`；其余模式归 #425/#431/#434/#437。
"""

from types import SimpleNamespace

import pytest

from ushareiplay.managers.playback.models import (
    PlaybackMode,
    PlaybackRequest,
)
from ushareiplay.managers.playback.player_page import PLAY_MODE_ELEMENT_KEYS
from ushareiplay.managers.playback.qq_music_ui_driver import QQMusicUIDriver


class _Element:
    """可点击元素的最小替身。"""

    def __init__(self):
        self.clicks = 0

    def click(self):
        self.clicks += 1


class _ElementFinder:
    def __init__(self, first_song):
        self.first_song = first_song
        self.requested = []

    def wait_for_element_clickable(self, key, timeout=None):
        self.requested.append(key)
        return self.first_song


class _QQMusicHandlerFake:
    """驱动实际使用的 QQMusicHandler 表面。

    只实现被驱动的 SONG 编排触达的方法；任何额外调用都会以 AttributeError
    暴露出来，避免测试在驱动悄悄多做事时仍然通过。
    """

    def __init__(self, playing_info=None, first_song=None):
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        self.playing_info = playing_info
        self.first_song = first_song if first_song is not None else _Element()
        self.prepared_queries = []
        self.favorited = []
        self._element_finder = _ElementFinder(self.first_song)

    @property
    def element_finder(self):
        return self._element_finder

    def _prepare_music_playback(self, music_query):
        self.prepared_queries.append(music_query)
        if isinstance(self.playing_info, Exception):
            raise self.playing_info
        return self.playing_info

    def ensure_favorited_in_playing_page(self, timeout=10):
        self.favorited.append(timeout)
        return True


# ---------------------------------------------------------------------------
# Slice 1: 未实现的播放模式
# ---------------------------------------------------------------------------


def test_driver_refuses_a_mode_it_does_not_implement_yet(initialized_test_singletons):
    """#425/#431/#434/#437 之前，非单曲模式必须响亮失败，而不是静默「播放成功」。"""
    handler = _QQMusicHandlerFake(playing_info={"song": "任意", "singer": "某", "album": "碟"})

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest(mode=PlaybackMode.RADAR, channel="sleep", requester="小明")
    )

    assert outcome.ok is False
    assert "radar" in outcome.error
    # 一个 UI 动作都不该发生：驱动连 handler 都没碰
    assert handler.prepared_queries == []


@pytest.mark.parametrize("mode", [m for m in PlaybackMode if m is not PlaybackMode.SONG])
def test_driver_reports_every_unimplemented_mode_as_failed(mode, initialized_test_singletons):
    handler = _QQMusicHandlerFake(playing_info={"song": "任意", "singer": "某", "album": "碟"})

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest(mode=mode, query="任意", requester="小明")
    )

    assert outcome.ok is False, f"{mode} 尚无生产实现，不该被当成播放成功"
    assert handler.prepared_queries == []


# ---------------------------------------------------------------------------
# Slice 2: 单曲点播
# ---------------------------------------------------------------------------


@pytest.fixture
def quality_checked(initialized_test_singletons):
    """记录质量过滤收到的曲目，避免测试真的去查发行日期。"""
    from ushareiplay.managers.music_manager import MusicManager

    seen = []
    MusicManager.initialize().handle_song_quality_check = seen.append
    return seen

def test_driver_clicks_the_first_match_and_reports_the_parsed_track(
    initialized_test_singletons, quality_checked
):
    handler = _QQMusicHandlerFake(
        playing_info={"song": "似是故人来", "singer": "梅艳芳", "album": "戏剧人生"}
    )

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.song("似是故人来 梅艳芳", requester="小明")
    )

    assert outcome.ok is True
    assert (outcome.track.song, outcome.track.singer, outcome.track.album) == (
        "似是故人来",
        "梅艳芳",
        "戏剧人生",
    )
    assert handler.prepared_queries == ["似是故人来 梅艳芳"]
    assert handler.first_song.clicks == 1


def test_driver_favorites_the_song_in_the_auto_opened_playing_page(
    initialized_test_singletons, quality_checked
):
    """播放页会自动弹出：不收藏的话，这首歌下次点播就搜不到了。"""
    handler = _QQMusicHandlerFake(
        playing_info={"song": "似是故人来", "singer": "梅艳芳", "album": "戏剧人生"}
    )

    QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.song("似是故人来 梅艳芳", requester="小明")
    )

    assert handler.favorited == [10]


def test_driver_hands_the_parsed_track_to_the_quality_filter(
    initialized_test_singletons, quality_checked
):
    """老歌过滤要在播放刚起来时立刻判一次，否则劣质版本会先响几秒。"""
    handler = _QQMusicHandlerFake(
        playing_info={"song": "如风", "singer": "王菲", "album": "十万个为什么"}
    )

    QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.song("如风 王菲", requester="小明")
    )

    assert quality_checked == [
        {"song": "如风", "singer": "王菲", "album": "十万个为什么"}
    ]


def test_driver_reports_the_song_missing_instead_of_raising(
    initialized_test_singletons, quality_checked
):
    """handler 用 {'error': ...} 表达「搜不到」；端口要求以返回值汇报，不是异常。"""
    handler = _QQMusicHandlerFake(playing_info={"error": "not found with query 不存在的歌"})

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.song("不存在的歌", requester="小明")
    )

    assert outcome.ok is False
    assert outcome.error == "not found with query 不存在的歌"
    assert handler.first_song.clicks == 0


def test_driver_reports_a_failed_search_when_the_handler_raises(
    initialized_test_singletons, quality_checked
):
    """Appium 层抛异常时必须转成 `failed` —— 抛出去会让房间停留在闭麦状态。"""
    handler = _QQMusicHandlerFake(playing_info=RuntimeError("session terminated"))

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.song("青花瓷", requester="小明")
    )

    assert outcome.ok is False
    assert "session terminated" in outcome.error


def test_driver_reports_the_result_row_missing_instead_of_raising(
    initialized_test_singletons, quality_checked
):
    handler = _QQMusicHandlerFake(
        playing_info={"song": "似是故人来", "singer": "梅艳芳", "album": "戏剧人生"}
    )
    handler._element_finder.first_song = None

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.song("似是故人来 梅艳芳", requester="小明")
    )

    assert outcome.ok is False
    assert "first song" in outcome.error


def test_driver_carries_the_release_date_the_quality_check_annotated(
    initialized_test_singletons
):
    """老歌过滤就地补上的发行日期必须随 outcome 上行，否则 `:play` 的回复日期会变空。

    迁移前命令返回的就是被就地改写过的那个 dict，所以回复里一直带着日期 ——
    只回 `PlaybackTrack` 三件套是一次真实的行为回退。
    """
    from ushareiplay.managers.music_manager import MusicManager

    def _annotate(song_info):
        song_info["release_date"] = "1993-09-07"

    MusicManager.initialize().handle_song_quality_check = _annotate
    handler = _QQMusicHandlerFake(
        playing_info={"song": "如风", "singer": "王菲", "album": "十万个为什么"}
    )

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.song("如风 王菲", requester="小明")
    )

    assert outcome.extra == {"release_date": "1993-09-07"}


def test_driver_leaves_the_release_date_out_when_the_quality_check_finds_none(
    initialized_test_singletons, quality_checked
):
    """查不到发行日期时不能输出 `release_date: None` —— 模板会渲染成字面量 "None"。"""
    handler = _QQMusicHandlerFake(
        playing_info={"song": "如风", "singer": "王菲", "album": "十万个为什么"}
    )

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest.song("如风 王菲", requester="小明")
    )

    assert dict(outcome.extra) == {}


# ---------------------------------------------------------------------------
# 组合根接线
# ---------------------------------------------------------------------------


def _real_config() -> dict:
    """真实 config.yaml：启动路径要的就是这份 selector 与命令表。"""
    from pathlib import Path

    import yaml

    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_composition_root_injects_the_production_driver(initialized_test_singletons):
    """真实跑一遍 `AppController._init_handlers()`，MusicManager 必须拿到生产适配器。

    漏装配不会在启动时炸，只会在第一次 `:play` 时抛 RuntimeError —— 那是线上才发现
    的故障，因此在这里钉住接线本身。走真实启动路径而非读源码。
    """
    from ushareiplay.core.app_controller import AppController
    from ushareiplay.core.singleton import Singleton
    from ushareiplay.managers.music_manager import MusicManager

    Singleton.reset_all_instances()
    AppController._ui_lock_owner = None
    AppController._ui_lock_depth = 0

    controller = AppController.__new__(AppController)
    controller.__init__(_real_config())
    controller.driver = SimpleNamespace()  # 构造函数只碰 driver 表面属性，不做设备 I/O
    controller._init_handlers()

    ui_driver = MusicManager.instance().ui_driver
    assert isinstance(ui_driver, QQMusicUIDriver)
    assert ui_driver._handler is controller.music_handler


# ---------------------------------------------------------------------------
# 播放模式切换（#423 收窄到端口上的第二个方法）
# ---------------------------------------------------------------------------


class _ModePageHandler:
    """播放页模式切换用的 handler 表面。

    `mode_sequence` 是每次重新读取播放页时依次观察到的模式 key 序列 —— 用它
    模拟「点一次没切过去、再点一次才切过去」。
    """

    def __init__(self, mode_sequence=("list",), clickable=True, switched=False):
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        self.mode_sequence = list(mode_sequence)
        self.clicks = 0
        self.reads = 0
        self.play_mode_key = "unknown"
        self.switched = switched
        self.key_actions = SimpleNamespace(
            switch_to_app=lambda: True, press_back=lambda: None
        )
        self.gesture_handler = SimpleNamespace(click_element_at=self._click)
        self._element_finder = SimpleNamespace(wait_for_any_element=self._wait_any)
        self._clickable = clickable

    def _click(self, _element):
        self.clicks += 1
        self.switched = True
        return self._clickable

    def _wait_any(self, keys):
        self.reads += 1
        index = min(self.reads - 1, len(self.mode_sequence) - 1)
        mode_key = self.mode_sequence[index]
        if mode_key is None:
            return None, None
        # `ensure_player_page` 谈的是元素 key（config.yaml 的 qq_music.elements），
        # 模式 key → 元素 key 的映射由 player_page 单点维护，替身不自己另编一套。
        return PLAY_MODE_ELEMENT_KEYS[mode_key], _Element()

    @property
    def element_finder(self):
        return self._element_finder

    def note_play_mode(self, mode_key, reason=""):
        self.play_mode_key = mode_key


def test_driver_reports_already_on_target_without_clicking_the_mode_button(
    initialized_test_singletons,
):
    """本来就是目标模式时一个点击都不该发生 —— 每次 `:mode` 都白点一下是骚扰。"""
    handler = _ModePageHandler(mode_sequence=["single"])

    outcome = QQMusicUIDriver(handler).set_play_mode("single")

    assert (outcome.ok, outcome.mode, outcome.already_target) == (True, "single", True)
    assert handler.clicks == 0


def test_driver_clicks_the_mode_button_until_the_page_shows_the_target(
    initialized_test_singletons,
):
    """第一次点击没生效时重读播放页并重试，而不是立刻报失败。"""
    handler = _ModePageHandler(mode_sequence=["list", "list", "single"])

    outcome = QQMusicUIDriver(handler).set_play_mode("single")

    assert (outcome.ok, outcome.mode, outcome.already_target) == (True, "single", False)
    assert handler.clicks == 2


def test_driver_records_the_observed_mode_into_the_room_cache(initialized_test_singletons):
    handler = _ModePageHandler(mode_sequence=["single"])

    QQMusicUIDriver(handler).set_play_mode("single")

    assert handler.play_mode_key == "single"


def test_driver_fails_when_nothing_is_playing(initialized_test_singletons):
    handler = _ModePageHandler(mode_sequence=[None])

    outcome = QQMusicUIDriver(handler).set_play_mode("single")

    assert outcome.ok is False
    assert handler.clicks == 0


def test_driver_fails_after_both_attempts_miss_the_target(initialized_test_singletons):
    """两次都没切过去是真实的失败，不能报成功 —— 房间会显示一个不成立的模式。"""
    handler = _ModePageHandler(mode_sequence=["list", "list", "list"])

    outcome = QQMusicUIDriver(handler).set_play_mode("single")

    assert outcome.ok is False
    assert outcome.mode == "list"
    assert handler.clicks == 2


def test_driver_reports_a_click_that_the_ui_refuses(initialized_test_singletons):
    """`click_element_at` 返回 False 时继续重试，两次都失败才报错。"""
    handler = _ModePageHandler(mode_sequence=["list", "list", "list"], clickable=False)

    outcome = QQMusicUIDriver(handler).set_play_mode("single")

    assert outcome.ok is False
    assert handler.clicks == 2


def test_driver_reports_a_mode_switch_exception_instead_of_raising(initialized_test_singletons):
    handler = _ModePageHandler()
    handler.gesture_handler.click_element_at = _ExplodingClick()

    outcome = QQMusicUIDriver(handler).set_play_mode("single")

    assert outcome.ok is False


class _ExplodingClick:
    def click_element_at(self, _element):
        raise RuntimeError("session terminated")
