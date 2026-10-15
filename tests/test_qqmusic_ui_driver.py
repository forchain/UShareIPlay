"""生产 `QQMusicUIDriver` 的离线测试。

测试面是端口上的四个方法：`start_playback(request)`、`set_play_mode(target)`、
`set_accompaniment(enable)` 与 `query_lyrics(query)`。QQMusicHandler 由测试模块内
的假替身提供 —— 替身只暴露驱动真正调用的那几个 UI 方法（查歌、点第一首、播放页
收藏、切前台、认播放页、点按钮、滚菜单），因此断言考的是「驱动怎么编排」而不是
「Appium 点了哪个坐标」。

`start_playback` 已实现的模式：`SONG`（#421）、`FAVORITES` 与 `RADAR`（#425）、
`PLAYLIST`（#434）、`RADIO`（#431）、`SINGER` 与 `ALBUM`（#437）；七种模式已全部交付。
各模式的编排测试见 `tests/test_favorites_radar_seam.py`、`tests/test_radio_seam.py`、
`tests/test_playlist_seam.py` 与 `tests/test_singer_album_seam.py`。
伴奏的两条 UI 通路（#427）都收在 `set_accompaniment` 后面：页上直接开关，以及
K歌入口只在「更多」菜单里那条要滚动着找的路。
"""

from types import SimpleNamespace

import pytest

from ushareiplay.managers.playback.models import (
    ACCOMPANIMENT_DISABLED_ERROR,
    NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR,
    PlaybackMode,
    PlaybackRequest,
)
from ushareiplay.managers.playback.player_page import (
    ACCOMPANIMENT_MENU_CONTAINER_KEY,
    ACCOMPANIMENT_MENU_KEY,
    ACCOMPANIMENT_MORE_ENTRY_KEY,
    ACCOMPANIMENT_ON_PAGE_KEYS,
    ACCOMPANIMENT_STATE_KEYS,
    ACCOMPANIMENT_SWITCH_KEY,
    PLAY_MODE_ELEMENT_KEYS,
)
from ushareiplay.managers.playback.qq_music_ui_driver import (
    PLAY_ALL_KEYS,
    PLAYLIST_RESULT_KEYS,
    QQMusicUIDriver,
)


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
    """未交付的模式必须响亮失败，而不是静默「播放成功」。

    已实现的模式（见 `IMPLEMENTED_MODES`）各有自己的编排测试；这里用一个真的
    还没交付的模式（RADIO，#431）守住「不认识的模式不假装成功」这条底线。
    """
    handler = _QQMusicHandlerFake(playing_info={"song": "任意", "singer": "某", "album": "碟"})

    outcome = QQMusicUIDriver(handler).start_playback(
        PlaybackRequest(mode=PlaybackMode.RADIO, query="任意", requester="小明")
    )

    assert outcome.ok is False
    assert "radio" in outcome.error
    # 一个 UI 动作都不该发生：驱动连 handler 都没碰
    assert handler.prepared_queries == []


# 已交付的模式：#421 单曲点播、#425 收藏与雷达、#434 歌单、#437 歌手与专辑。
IMPLEMENTED_MODES = (
    PlaybackMode.SONG,
    PlaybackMode.FAVORITES,
    PlaybackMode.RADAR,
    PlaybackMode.PLAYLIST,
    PlaybackMode.SINGER,
    PlaybackMode.ALBUM,
)


@pytest.mark.parametrize(
    "mode", [m for m in PlaybackMode if m not in IMPLEMENTED_MODES]
)
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


# ---------------------------------------------------------------------------
# 伴奏开关（#427 的两条通路收在同一个端口方法后面）
# ---------------------------------------------------------------------------


class _SwitchElement:
    """K歌入口元素：`enabled` 属性决定伴奏模式有没有被激活。"""

    def __init__(self, enabled="true"):
        self._enabled = enabled

    def get_attribute(self, name):
        assert name == "enabled", f"K歌入口只该被问 enabled，实际问的是 {name}"
        return self._enabled


class _AccompanimentHandler:
    """伴奏开关用的 handler 表面。

    `found_key` 是进播放页后认出的那个控件：`accompaniment_text_off` 是页上直接有
    开关的那一版 App，`more_entry` 是 K歌入口只在「更多」菜单里的那一版。
    `state_key` 是菜单打开后亮着「伴唱已开启/已关闭」的那枚状态按钮；
    `menu_found=False` 模拟菜单项滚不出来，`playing=False` 模拟没有音乐在放。

    替身刻意只实现被驱动的编排真正触达的方法：驱动多走一步（比如忘了按返回键
    收起菜单），这里就会以 AttributeError 暴露出来。
    """

    def __init__(
        self,
        found_key=ACCOMPANIMENT_MORE_ENTRY_KEY,
        *,
        state_key="accompaniment_button_off",
        switch_enabled="true",
        menu_found=True,
        playing=True,
    ):
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        self.found_key = found_key
        self.found_element = _Element()
        self.switch_element = _SwitchElement(switch_enabled)
        self.menu_element = _Element()
        self.state_key = state_key
        self.state_element = _Element()
        self.menu_found = menu_found
        self.playing = playing
        self.clicks = []
        self.switch_lookups = []
        self.scrolls = []
        self.state_lookups = []
        self.backs = 0
        self.switched_to_app = False
        self.key_actions = SimpleNamespace(
            switch_to_app=self._switch_to_app, press_back=self._press_back
        )
        self.gesture_handler = SimpleNamespace(
            click_element_at=self._click_at,
            scroll_container_until_element=self._scroll_until,
        )
        self._element_finder = SimpleNamespace(
            wait_for_any_element=self._wait_any,
            try_find_element=self._try_find,
        )

    @property
    def element_finder(self):
        return self._element_finder

    def _switch_to_app(self):
        self.switched_to_app = True
        return True

    def _press_back(self):
        self.backs += 1

    def _wait_any(self, keys):
        if ACCOMPANIMENT_MORE_ENTRY_KEY in keys:
            # 「站在播放页上」的那次探测：认出声称控件或「更多」入口。
            if not self.playing:
                return None, None
            return self.found_key, self.found_element
        # 菜单打开后认伴唱开/关的那枚状态按钮。
        self.state_lookups.append(tuple(keys))
        return self.state_key, self.state_element

    def _try_find(self, key):
        self.switch_lookups.append(key)
        return self.switch_element

    def _click_at(self, element):
        self.clicks.append(element)
        return True

    def _scroll_until(self, element_key, container_key, *args, **kwargs):
        self.scrolls.append((element_key, container_key))
        if not self.menu_found:
            return None, None, []
        return element_key, self.menu_element, []


def test_driver_walks_the_more_menu_path_and_toggles_the_switch(initialized_test_singletons):
    """K歌入口只在「更多」菜单里：整条导航都得真的走一遍，替身才谈得上验证。"""
    handler = _AccompanimentHandler(
        found_key=ACCOMPANIMENT_MORE_ENTRY_KEY,
        state_key="accompaniment_button_off",
    )

    outcome = QQMusicUIDriver(handler).set_accompaniment(True)

    assert (outcome.ok, outcome.enabled, outcome.already_target) == (True, True, False)
    # 进播放页的仪式、点「更多」、滚菜单、点菜单项、拨开关、收起菜单，一样不少。
    assert handler.switched_to_app is True
    assert handler.switch_lookups == [ACCOMPANIMENT_SWITCH_KEY]
    assert handler.scrolls == [(ACCOMPANIMENT_MENU_KEY, ACCOMPANIMENT_MENU_CONTAINER_KEY)]
    assert handler.menu_element.clicks == 1
    assert handler.clicks == [handler.found_element, handler.state_element]
    assert handler.state_lookups == [ACCOMPANIMENT_STATE_KEYS]
    # 仪式自己按一次、收起菜单再按一次；菜单不收起会一直挡着后面的 UI。
    assert handler.backs == 2


def test_driver_leaves_the_menu_alone_when_the_switch_is_already_where_it_should_be(
    initialized_test_singletons,
):
    """菜单里本来就是伴唱已开启：拨动按钮不点，但菜单照样要收起。"""
    handler = _AccompanimentHandler(
        found_key=ACCOMPANIMENT_MORE_ENTRY_KEY,
        state_key="accompaniment_button_on",
    )

    outcome = QQMusicUIDriver(handler).set_accompaniment(True)

    assert (outcome.ok, outcome.enabled, outcome.already_target) == (True, True, True)
    assert handler.clicks == [handler.found_element]
    assert handler.backs == 2


def test_driver_refuses_an_accompaniment_switch_that_the_app_greyed_out(
    initialized_test_singletons,
):
    """K歌入口整体灰掉：伴奏模式压根没被激活，如实回那句既有文案，一个点击都不发生。"""
    handler = _AccompanimentHandler(
        found_key=ACCOMPANIMENT_MORE_ENTRY_KEY, switch_enabled="false"
    )

    outcome = QQMusicUIDriver(handler).set_accompaniment(True)

    assert outcome.ok is False
    assert outcome.error == ACCOMPANIMENT_DISABLED_ERROR
    assert ACCOMPANIMENT_DISABLED_ERROR == "Accompaniment mode is disabled"
    assert handler.switch_lookups == [ACCOMPANIMENT_SWITCH_KEY]
    assert handler.clicks == []
    assert handler.scrolls == []


def test_driver_toggles_the_direct_switch_without_opening_the_menu(initialized_test_singletons):
    """播放页上直接显示伴唱状态：点那行文案即切换，不必进「更多」菜单。"""
    handler = _AccompanimentHandler(found_key="accompaniment_text_off")

    outcome = QQMusicUIDriver(handler).set_accompaniment(True)

    assert (outcome.ok, outcome.enabled, outcome.already_target) == (True, True, False)
    assert handler.clicks == [handler.found_element]
    assert handler.scrolls == []


def test_driver_does_not_click_the_direct_switch_when_it_already_matches(
    initialized_test_singletons,
):
    """本来就是目标状态：一个点击都不该发生（否则每次 `:acc 1` 都白点一下）。"""
    handler = _AccompanimentHandler(found_key="accompaniment_text_on")

    outcome = QQMusicUIDriver(handler).set_accompaniment(True)

    assert (outcome.ok, outcome.enabled, outcome.already_target) == (True, True, True)
    assert handler.clicks == []


def test_driver_reports_the_accompaniment_no_music_wording(initialized_test_singletons):
    """同一个「没有音乐在放」，伴奏那句英文文案一个字都不能改。"""
    handler = _AccompanimentHandler(playing=False)

    outcome = QQMusicUIDriver(handler).set_accompaniment(True)

    assert outcome.ok is False
    assert outcome.error == NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR
    assert NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR == (
        "No music playing, cannot toggle accompaniment mode"
    )
    assert handler.clicks == []


def test_driver_probes_the_accompaniment_keys_rather_than_the_play_mode_ones(
    initialized_test_singletons,
):
    """伴奏认「已经在播放页上」的证据与播放模式不同：认错 key 会一直报「没在放歌」。"""
    handler = _AccompanimentHandler()

    QQMusicUIDriver(handler).set_accompaniment(True)

    probed = handler.state_lookups[0]
    assert probed == ACCOMPANIMENT_STATE_KEYS
    assert set(ACCOMPANIMENT_ON_PAGE_KEYS) & set(probed) == set()


def test_driver_reports_an_accompaniment_switch_exception_instead_of_raising(
    initialized_test_singletons,
):
    handler = _AccompanimentHandler()
    handler.gesture_handler.click_element_at = _ExplodingClick()

    outcome = QQMusicUIDriver(handler).set_accompaniment(True)

    assert outcome.ok is False


# ---------------------------------------------------------------------------
# 歌词查询（#430 收窄到端口上的第三个方法）
# ---------------------------------------------------------------------------


class _LyricsHandler:
    """歌词查询用的 handler 表面。

    `lyrics_text` 模拟 DOM 里读到的原文，故意带 HTML 实体：解不开就会把
    `&amp;` 原样发进房间公屏。
    """

    def __init__(self, found=True, text="第一行&amp;第二行<br>第三行"):
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        self.found = found
        self.text = text
        self.switched_to_app = False
        self.queries = []
        self.key_actions = SimpleNamespace(switch_to_app=self._switch)
        self._element_finder = SimpleNamespace(wait_for_any_element=self._wait_any)

    def _switch(self):
        self.switched_to_app = True
        return True

    def _wait_any(self, keys):
        if not self.found:
            return "not_found", _Element()
        return "lyrics_text", _TextElement(self.text)

    @property
    def element_finder(self):
        return self._element_finder

    def query_music(self, query):
        self.queries.append(query)
        return "search_box"


class _TextElement(_Element):
    def __init__(self, text):
        super().__init__()
        self.text = text


@pytest.fixture
def lyrics_tab(initialized_test_singletons):
    """记录歌词分类 tab 的选择结果，避免测试真的去切 tab。"""
    from ushareiplay.managers.music_manager import MusicManager

    calls = []
    manager = MusicManager.initialize()
    manager.select_tab = lambda name, **kwargs: calls.append(name) or True
    return calls


def test_driver_unescapes_html_entities_in_the_lyrics(initialized_test_singletons, lyrics_tab):
    handler = _LyricsHandler()

    outcome = QQMusicUIDriver(handler).query_lyrics("青花瓷")

    assert (outcome.ok, outcome.text) == (True, "第一行&第二行<br>第三行")


def test_driver_brings_the_app_forward_before_searching(initialized_test_singletons, lyrics_tab):
    handler = _LyricsHandler()

    QQMusicUIDriver(handler).query_lyrics("青花瓷")

    assert handler.switched_to_app is True
    assert handler.queries == ["青花瓷"]
    assert lyrics_tab == ["lyrics"]


def test_driver_reports_no_lyrics_as_a_clean_failure(initialized_test_singletons, lyrics_tab):
    """没有歌词是正常结局，必须是可回复的 `failed`，不是异常。"""
    handler = _LyricsHandler(found=False)

    outcome = QQMusicUIDriver(handler).query_lyrics("青花瓷")

    assert outcome.ok is False
    assert "青花瓷" in outcome.error


def test_driver_reports_a_lyrics_search_exception_instead_of_raising(initialized_test_singletons, lyrics_tab):
    handler = _LyricsHandler()

    def _boom(_query):
        raise RuntimeError("session terminated")

    handler.query_music = _boom

    outcome = QQMusicUIDriver(handler).query_lyrics("青花瓷")

    assert outcome.ok is False
    assert "session terminated" in outcome.error


# ---------------------------------------------------------------------------
# 歌单播放（#434：`:playlist <query>` 收在 start_playback 里，不拓宽端口）
# ---------------------------------------------------------------------------


class _Row(_Element):
    """歌单详情页里的一行：第一列歌名、第二列歌手。"""

    def __init__(self, text):
        super().__init__()
        self.text = text


class _TrackItem:
    """`result_item` 容器：按 LinearLayout 分列，第一列是歌名、第二列是歌手。"""

    def __init__(self, rows):
        self._rows = [_Row(text) for text in rows]
        self.lookups = []

    def find_elements(self, by, value):
        self.lookups.append((by, value))
        return self._rows


def _playlist_request(query, requester="小明"):
    """构造歌单模式的请求。

    刻意直接构造而不是调 `PlaybackRequest.playlist(...)`：本数据类的 `playlist`
    是**字段**（写进房间 `current_playlist_name` 的那个），同名 classmethod 会顶掉
    字段的类级默认值。命令层因此也只能直接构造。
    """
    return PlaybackRequest(
        mode=PlaybackMode.PLAYLIST, query=query, requester=requester
    )


class _PlaylistHandler:
    """歌单播放用的 handler 表面。

    旋钮对应这条编排上每个可能失败的关节：`query_found`（搜得到吗）、
    `tab_available`（切得到歌单分类吗）、`found_key`（结果页认出的是歌单卡片还是
    「没有找到」提示）、`play_all_key`（认出的播放全部按钮）、`playlist_info`
    （点完播放全部之后读回来的队列）。

    替身只实现被驱动的编排真正触达的方法：驱动多走一步（例如忘了点播放全部就
    读队列），这里就会以 AttributeError 暴露出来。
    """

    def __init__(
        self,
        *,
        playlist_name="学习|英语",
        query_found=True,
        tab_available=True,
        found_key="playlist_result",
        first_track=("似是故人来", "梅艳芳"),
        play_all_key="play_all",
        playlist_info=None,
    ):
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        self.playlist_name = playlist_name
        self.query_found = query_found
        self.tab_available = tab_available
        self.found_key = found_key
        self.play_all_key = play_all_key
        self.track_item = None if first_track is None else _TrackItem(list(first_track))
        self.playlist_info = (
            {"playlist": "似是故人来 - 梅艳芳\n如风 - 王菲"}
            if playlist_info is None
            else playlist_info
        )

        self.queries = []
        self.card = _TextElement(playlist_name)
        self.play_button = _Element()
        self.result_card = _Element()
        self.result_card.text = playlist_name
        self.queue_reads = 0

        self._element_finder = SimpleNamespace(
            wait_for_any_element=self._wait_any,
            try_find_element=self._try_find,
        )

    @property
    def element_finder(self):
        return self._element_finder

    def query_music(self, query):
        self.queries.append(query)
        return "search_box" if self.query_found else None

    def _wait_any(self, keys):
        if keys == PLAYLIST_RESULT_KEYS:
            return self.found_key, self.result_card if self.found_key != "not_found" else _Element()
        if keys == PLAY_ALL_KEYS:
            return self.play_all_key, self.play_button if self.play_all_key else None
        raise AssertionError(f"unexpected keys: {keys}")

    def _try_find(self, key):
        if key == "result_item":
            return self.track_item
        raise AssertionError(f"unexpected key: {key}")

    def get_playlist_info(self):
        self.queue_reads += 1
        return self.playlist_info


@pytest.fixture
def playlist_tab(initialized_test_singletons):
    """脚本化的分类 tab 选择：驱动只看到 True/False，这里负责记录与注入。"""
    from ushareiplay.managers.music_manager import MusicManager

    class _TabSelection:
        def __init__(self):
            self.calls = []
            self.available = True

        def __call__(self, name, **kwargs):
            self.calls.append(name)
            return self.available

    tabs = _TabSelection()
    MusicManager.initialize().select_tab = tabs
    return tabs


def test_driver_walks_the_whole_playlist_flow_and_reports_what_it_saw(
    initialized_test_singletons, playlist_tab
):
    """查歌 → 切歌单分类 → 点卡片 → 点播放全部 → 读队列，一步都不能少。"""
    handler = _PlaylistHandler()

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("学习", requester="小明")
    )

    assert outcome.ok is True
    assert handler.queries == ["学习"]
    assert playlist_tab.calls == ["playlist"]
    assert handler.result_card.clicks == 1
    assert handler.play_button.clicks == 1
    assert handler.queue_reads == 1


def test_driver_hands_the_engine_the_room_title_topic_and_playlist_it_parsed(
    initialized_test_singletons, playlist_tab
):
    """`PlaybackOutcome` 上的三项都是 UI 上读到的事实：房名/话题归一歌单名，歌单名原样。"""
    handler = _PlaylistHandler(playlist_name="学习|英语")

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("学习", requester="小明")
    )

    assert (outcome.title, outcome.topic, outcome.playlist) == ("学习", "英语", "学习|英语")


def test_driver_carries_the_queue_text_the_reply_renders(
    initialized_test_singletons, playlist_tab
):
    """`:playlist` 的回复模板是纯 `{playlist}`，它渲染的必须是播放队列本身。

    因此走 `extra` 而不是 `PlaybackOutcome.playlist`：后者写进房间的
    `current_playlist_name`，要保持歌单卡片上的原文，不是队列行。
    """
    handler = _PlaylistHandler(playlist_info={"playlist": "似是故人来 - 梅艳芳\n如风 - 王菲"})

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("学习", requester="小明")
    )

    assert outcome.extra["playlist"] == "似是故人来 - 梅艳芳\n如风 - 王菲"


def test_driver_falls_back_to_the_playlist_name_when_the_queue_cannot_be_read(
    initialized_test_singletons, playlist_tab
):
    """读不到队列是正常结局：歌已经在放，回复退回歌单名，而不是整条失败。"""
    handler = _PlaylistHandler(playlist_info={"error": "No songs found in playlist"})

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("学习", requester="小明")
    )

    assert outcome.ok is True
    assert outcome.extra["playlist"] == "学习|英语"


def test_driver_reports_a_missing_match_instead_of_starting_anything(
    initialized_test_singletons, playlist_tab
):
    """「没有找到与…」是与「播放全部按钮不见了」不同的两件事，都不该响一次播放。"""
    handler = _PlaylistHandler(found_key="not_found")

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("不存在的歌单", requester="小明")
    )

    assert outcome.ok is False
    assert "不存在的歌单" in outcome.error
    assert handler.play_button.clicks == 0


def test_driver_reports_a_missing_play_all_button(initialized_test_singletons, playlist_tab):
    """认出了歌单却没有「播放全部」：点开了详情页但一首都没放，如实报失败。"""
    handler = _PlaylistHandler(play_all_key=None)

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("学习", requester="小明")
    )

    assert outcome.ok is False
    assert handler.queue_reads == 0


def test_driver_reports_a_playlist_search_that_found_nothing(initialized_test_singletons, playlist_tab):
    """`query_music` 返回 None（搜索框都没进去）时连歌单分类都不该切。"""
    handler = _PlaylistHandler(query_found=False)

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("学习", requester="小明")
    )

    assert outcome.ok is False
    assert playlist_tab.calls == []


def test_driver_reports_a_playlist_flow_exception_instead_of_raising(initialized_test_singletons, playlist_tab):
    handler = _PlaylistHandler()

    def _boom(_keys):
        raise RuntimeError("session terminated")

    handler._element_finder.wait_for_any_element = _boom

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("学习", requester="小明")
    )

    assert outcome.ok is False
    assert "session terminated" in outcome.error


def test_driver_reports_the_missing_playlist_tab(initialized_test_singletons, playlist_tab):
    """切不到歌单分类是用户能据以行动的失败：回「找不到歌单分类」，而不是静默继续。"""
    playlist_tab.available = False
    handler = _PlaylistHandler()

    outcome = QQMusicUIDriver(handler).start_playback(
        _playlist_request("学习", requester="小明")
    )

    assert outcome.ok is False
    assert playlist_tab.calls == ["playlist"]
    assert handler.result_card.clicks == 0
