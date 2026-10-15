"""`PlaybackMode.RADIO` 的接缝测试（#431）。

被测的三条接缝 —— 断言只落在这些公开入口上，不碰驱动内部的 helper 名字：

1. `QQMusicUIDriver.start_playback()` —— 五个电台频道各自的 UI 编排；
2. `RadioCommand.do_process()` —— 子命令 → `PlaybackRequest` 的翻译，
   以及「命令层不再自己守护、不再自己采纳」；
3. `MusicManager.play()` —— 被歌单守护拒绝时，零 UI 动作、零麦克风动作。

全部离线：QQMusicHandler 是模块内的假替身，命令层用
`InMemoryMusicUIDriver`，不需要 Appium、真机或 `dumpsys`。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import StaleElementReferenceException

from ushareiplay.commands.radio import RadioCommand
from ushareiplay.managers.playback.models import PlaybackMode, PlaybackRequest
from ushareiplay.managers.playlist_adoption import primary_topic
from ushareiplay.models.message_info import MessageInfo

# 老歌过滤的判定基准。与 config.yaml 的默认值一致，让测试里的「1995 年」
# 与「2021 年」分别落在截止线两侧。
OLD_SONG_CUTOFF = "2000-01-01"


class _InfoManager:
    """InfoManager 替身：歌单守护判定 + 房间播放者状态。"""

    def __init__(self, protection_error=None):
        self.protection_error = protection_error
        self.player_name = None
        self.current_playlist_name = None

    async def check_playlist_protection(self, requester, config=None):
        """`PlaylistAdoption.guard_switch` 要的是错误 dict，不是字符串。"""
        return {"error": self.protection_error} if self.protection_error else None


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


class _RecordingMicManager:
    """记录真实开闭麦动作；默认在麦上，静音保护一旦触发就一定有事件。"""

    def __init__(self, journal):
        self.journal = journal
        self._state = True

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


def _controller():
    return SimpleNamespace(
        soul_handler=MagicMock(),
        music_handler=MagicMock(),
        config={},
    )


@pytest.fixture
def radio_engine(initialized_test_singletons):
    """`:radio` 的引擎台：真守护 + 真房间同步 + 内存 UI 驱动。

    守护判定仍由 `PlaylistAdoption.guard_switch` 发给替身的 `_InfoManager`，
    因此「守护还管不管得住 `:radio`」考的是引擎与命令的接线，而不是命令层
    有没有再自己判一次。驱动替身把房间标题/话题/歌单都报成固定值，好让
    「驱动观察到的事实一路进了房间」这件事看得见。
    """
    from ushareiplay.managers.music_manager import MusicManager
    from ushareiplay.managers.playback_muting import PlaybackMuting
    from ushareiplay.managers.playlist_adoption import PlaylistAdoption
    from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver

    journal = []
    driver = InMemoryMusicUIDriver(
        journal=journal,
        titles={PlaybackMode.RADIO: "每日猜你喜欢"},
        topics={PlaybackMode.RADIO: "新歌"},
        playlists={PlaybackMode.RADIO: "每日猜你喜欢"},
    )

    adoption = PlaylistAdoption.instance()
    adoption._info = _InfoManager()
    adoption._room_profile = _RoomProfileManager()
    adoption._music = SimpleNamespace(list_mode=None, no_skip=0)

    MusicManager.initialize(ui_driver=driver)
    PlaybackMuting.initialize(
        SimpleNamespace(logger=MagicMock(), config={}),
        SimpleNamespace(wait_for_playback_ready=lambda **_kw: True),
        _RecordingMicManager(journal),
    )
    return SimpleNamespace(
        driver=driver,
        journal=journal,
        info=adoption._info,
        room_profile=adoption._room_profile,
    )


# ---------------------------------------------------------------------------
# Slice 1: 命令层是薄适配器
# ---------------------------------------------------------------------------


async def test_bare_radio_defaults_to_the_collection_channel(radio_engine):
    """裸 `:radio` 等于 `:radio collection` —— 频道走 `PlaybackRequest.channel`。"""
    command = RadioCommand(_controller())

    result = await command.do_process(
        MessageInfo(content="/radio", nickname="Timer"), []
    )

    assert len(radio_engine.driver.requests) == 1
    request = radio_engine.driver.requests[0]
    assert request.mode is PlaybackMode.RADIO
    assert request.channel == "collection"
    assert request.requester == "Timer"
    assert "error" not in result


@pytest.mark.parametrize(
    "channel", ["guess", "daily", "collection", "sleep", "radar"]
)
async def test_every_radio_channel_is_carried_on_the_request(radio_engine, channel):
    command = RadioCommand(_controller())

    result = await command.do_process(
        MessageInfo(content=f"/radio {channel}", nickname="小明"), [channel]
    )

    assert len(radio_engine.driver.requests) == 1
    request = radio_engine.driver.requests[0]
    assert request.mode is PlaybackMode.RADIO
    assert request.channel == channel
    assert "error" not in result


async def test_unknown_radio_channel_is_reported_as_an_error(radio_engine):
    command = RadioCommand(_controller())

    result = await command.do_process(
        MessageInfo(content="/radio nope", nickname="小明"), ["nope"]
    )

    assert "error" in result
    assert radio_engine.driver.requests == [], "频道不认识就不该驱动 UI"


async def test_radio_does_not_mute_at_command_level(initialized_test_singletons):
    """麦克风生命周期归引擎的切歌边界，命令层不再声明参与。"""
    assert RadioCommand.playback_muting is False


# ---------------------------------------------------------------------------
# Slice 2: 驱动里的五个频道
#
# QQMusicHandler 由下面的假替身提供，替身只暴露驱动真正调用的那几个 UI 方法，
# 因此断言考的是「驱动怎么编排这个频道」，不是 Appium 点了哪个坐标。
# ---------------------------------------------------------------------------


class _FakeElement:
    def __init__(self, key, text="", actions=None, attrs=None, texts=None, stale_reads=0):
        self.key = key
        self.attrs = attrs or {}
        self.clicks = 0
        self.stale_reads = stale_reads
        self.on_click = None
        self._actions = actions if actions is not None else []
        self._texts = list(texts) if texts else None
        self._text = text

    @property
    def text(self):
        """读一次就换一句 —— 用来模拟频道自己刷新卡片之后推荐歌名变了。"""
        if self.stale_reads:
            self.stale_reads -= 1
            raise StaleElementReferenceException("stale")
        if self._texts:
            return self._texts.pop(0)
        return self._text

    def click(self):
        self.clicks += 1
        self._actions.append(f"click:{self.key}")
        if self.on_click is not None:
            self.on_click()


class _FakeElementFinder:
    def __init__(self, elements, actions):
        self._elements = elements
        self._actions = actions
        self._hidden = set()
        self.attrs_seen = []

    def hide(self, key):
        """把一个元素从界面上拿掉 —— 频道状态切换就是这么表现的。"""
        self._hidden.add(key)

    def show(self, key):
        self._hidden.discard(key)

    def _visible(self, key):
        return None if key in self._hidden else self._elements.get(key)

    def wait_for_element_clickable(self, key, timeout=None):
        self._actions.append(f"wait_clickable:{key}")
        return self._visible(key)

    def wait_for_element(self, key, timeout=None):
        self._actions.append(f"wait:{key}")
        return self._visible(key)

    def wait_for_any_element(self, keys, timeout=None):
        self._actions.append(f"wait_any:{'/'.join(keys)}")
        for key in keys:
            element = self._visible(key)
            if element is not None:
                return key, element
        return "not_found", None

    def try_find_element(self, key, log=True):
        self._actions.append(f"try_find:{key}")
        return self._visible(key)

    def try_get_attribute(self, element, name):
        self._actions.append(f"attr:{name}")
        self.attrs_seen.append(name)
        return element.attrs.get(name)


class _RadioHandlerFake:
    """QQMusicHandler 替身：只给驱动调用的那几个方法。"""

    def __init__(self, elements, actions, queue="", switch_ok=True, home_ok=True):
        self.logger = MagicMock()
        self.elements = elements
        self.queue = queue
        self._actions = actions
        self._switch_ok = switch_ok
        self._home_ok = home_ok
        self.key_actions = SimpleNamespace(switch_to_app=self._switch)
        self.element_finder = _FakeElementFinder(elements, actions)
        self.gesture_handler = SimpleNamespace(
            scroll_container_until_element=self._scroll_until
        )

    def _switch(self):
        self._actions.append("switch:qq")
        return self._switch_ok

    def _scroll_until(self, key, container, direction, by, text, max_swipes=0):
        self._actions.append(f"scroll_until:{key}/{text}")
        return True, self.elements.get(f"tab:{text}"), None

    def navigate_to_home(self):
        self._actions.append("home")
        return self._home_ok

    def get_playlist_info(self):
        self._actions.append("queue")
        return {"playlist": self.queue} if self.queue else {"error": "queue unavailable"}


class _ReleaseLookup:
    """发行日期查询替身：按曲目名给日期，未登记的当作查不到。"""

    def __init__(self, dates):
        self.dates = dates
        self.queries = []

    def get_release_date(self, query):
        self.queries.append(query)
        return self.dates.get(query)


@pytest.fixture
def music_manager(initialized_test_singletons):
    """驱动里的老歌判定要走真实的 `MusicManager`，这里只换掉它的日期查询。"""
    from ushareiplay.managers.music_manager import MusicManager

    manager = MusicManager.initialize()
    manager.music_handler = SimpleNamespace(config={})
    manager._song_release_lookup = _ReleaseLookup({})
    return manager


def _filter_config(**overrides):
    config = {"enabled": True, "cutoff_date": OLD_SONG_CUTOFF}
    config.update(overrides)
    return {"old_song_filter": config}


def _driver(elements, actions, setup=None, **kwargs):
    from ushareiplay.managers.playback.qq_music_ui_driver import QQMusicUIDriver

    handler = _RadioHandlerFake(elements, actions, **kwargs)
    if setup is not None:
        setup(handler)
    return QQMusicUIDriver(handler), handler


def _radio(channel, **kwargs):
    return PlaybackRequest(mode=PlaybackMode.RADIO, channel=channel, **kwargs)


def test_guess_channel_opens_the_guess_station(music_manager):
    actions = []
    driver, _ = _driver(
        {
            "guess_title": _FakeElement("guess_title", "每日猜你喜欢", actions),
            "guess_topic": _FakeElement("guess_topic", "新歌 - 歌手甲", actions),
        },
        actions,
        queue="新歌 - 歌手甲\n老歌 - 歌手乙",
    )

    outcome = driver.start_playback(_radio("guess"))

    assert outcome.ok
    assert actions == [
        "switch:qq",
        "home",
        "wait_clickable:guess_title",
        "wait:guess_topic",
        "click:guess_title",
        "queue",
    ]
    assert outcome.title == "每日猜你喜欢"
    assert outcome.topic == "新歌"
    assert outcome.playlist == "每日猜你喜欢"
    assert outcome.extra["playlist"] == "新歌 - 歌手甲\n老歌 - 歌手乙"


def test_daily_channel_plays_the_daily_thirty(music_manager):
    actions = []
    driver, _ = _driver(
        {
            "daily_title": _FakeElement("daily_title", "每日30首", actions),
            "daily_topic": _FakeElement("daily_topic", "新歌", actions),
            "play_all": _FakeElement("play_all", actions=actions),
        },
        actions,
        queue="新歌 - 歌手甲\n老歌 - 歌手乙",
    )

    outcome = driver.start_playback(_radio("daily"))

    assert outcome.ok
    assert actions == [
        "switch:qq",
        "home",
        "wait_clickable:daily_title",
        "wait:daily_topic",
        "click:daily_title",
        "wait_clickable:play_all",
        "click:play_all",
        "queue",
    ]
    assert outcome.title == "每日30首"
    # 话题取队列第一行的歌名，而不是卡片上的频道名。
    assert outcome.topic == "新歌"
    assert outcome.playlist == "每日30首"
    assert outcome.extra["playlist"] == "新歌 - 歌手甲\n老歌 - 歌手乙"


def test_sleep_channel_scrolls_to_the_healing_tab(music_manager):
    actions = []
    driver, _ = _driver(
        {
            "tab:疗愈": _FakeElement("tab:疗愈", actions=actions),
            "play_healing": _FakeElement("play_healing", actions=actions),
        },
        actions,
        queue="摇篮曲 - 歌手甲",
    )

    outcome = driver.start_playback(_radio("sleep"))

    assert outcome.ok
    assert actions == [
        "switch:qq",
        "home",
        "scroll_until:home_tab_label/疗愈",
        "click:tab:疗愈",
        "wait_clickable:play_healing",
        "click:play_healing",
        "queue",
        "home",
    ]
    assert outcome.title == "音乐疗愈"
    # 驱动报整行队列（那是它观察到的事实），按 `" - "` 取前半段是 adopt 的归一化。
    assert outcome.topic == "摇篮曲 - 歌手甲"
    assert primary_topic(outcome.topic) == "摇篮曲"
    assert outcome.playlist == "音乐疗愈"
    assert outcome.extra["playlist"] == "摇篮曲 - 歌手甲"


def test_radar_channel_reads_the_streaming_song(music_manager):
    actions = []
    driver, _ = _driver(
        {
            "radar_nav": _FakeElement("radar_nav", actions=actions),
            "radar_song": _FakeElement("radar_song", "正在播出", actions),
            "radar_singer": _FakeElement("radar_singer", "歌手甲", actions),
        },
        actions,
        queue="正在播出 - 歌手甲",
    )

    outcome = driver.start_playback(_radio("radar"))

    assert outcome.ok
    assert actions == [
        "switch:qq",
        "home",
        "try_find:radar_nav",
        "click:radar_nav",
        "wait_clickable:radar_song",
        "wait_clickable:radar_singer",
        "queue",
    ]
    assert outcome.title == "O Radio"
    assert outcome.topic == "正在播出"
    assert outcome.playlist == "O Radio"
    assert outcome.track.song == "正在播出"
    assert outcome.track.singer == "歌手甲"
    assert outcome.extra["playlist"] == "正在播出 - 歌手甲"


def test_unknown_channel_fails_loudly_without_touching_the_ui(music_manager):
    actions = []
    driver, _ = _driver({}, actions)

    outcome = driver.start_playback(_radio("nope"))

    assert not outcome.ok
    assert "nope" in outcome.error
    assert actions == [], "频道不认识就不该驱动任何 UI"


# ---------------------------------------------------------------------------
# Slice 3: 精选频道 —— 唯一一处「老歌就换一首」的编排
# ---------------------------------------------------------------------------


# 精选卡片的无障碍标题：频道名 + 书名号里的本期甄选 + 控件说明。
# 三段尾巴都要被裁掉，房名才轮得到「每周甄选」。
COLLECTION_CARD_DESC = "精选「每周甄选」 音频按钮 更多"


def _collection_elements(actions, topic_text="新歌 - 歌手甲", playing=False, **kwargs):
    """精选频道首页卡片上的元素。

    `playing=True` 表示频道正在播「精选」：按钮文案此时是「暂停」，点开卡片不会
    换歌，得先回首页让频道换一首 —— 于是 `pause_collection` 在界面上、`play_collection`
    藏着，直到 `home_nav` 被点掉。
    """
    elements = {
        "play_collection": _FakeElement("play_collection", actions=actions),
        "pause_collection": _FakeElement("pause_collection", actions=actions),
        "home_nav": _FakeElement("home_nav", actions=actions),
        "collection_title": _FakeElement(
            "collection_title", actions=actions,
            attrs={"content-desc": COLLECTION_CARD_DESC},
        ),
        "collection_topic": _FakeElement(
            "collection_topic", text=topic_text, actions=actions, **kwargs
        ),
    }
    return elements


def _collection_setup(playing=False):
    """把频道的状态表现成界面上的显示/隐藏。"""

    def setup(handler):
        finder = handler.element_finder
        if playing:
            # 正在播：卡片上只有「暂停」，点开不会换歌。
            finder.hide("play_collection")
        else:
            # 没在播：卡片上只有「播放」，一点就换歌。
            finder.hide("pause_collection")

        def leave_collection():
            finder.hide("pause_collection")
            finder.show("play_collection")

        handler.elements["home_nav"].on_click = leave_collection

    return setup


def test_collection_channel_plays_the_station(music_manager):
    actions = []
    music_manager.music_handler.config = _filter_config()
    music_manager._song_release_lookup = _ReleaseLookup({"新歌": "2021-05-01"})
    driver, _ = _driver(
        _collection_elements(actions), actions, setup=_collection_setup(),
        queue="新歌 - 歌手甲\n老歌 - 歌手乙",
    )

    outcome = driver.start_playback(_radio("collection"))

    assert outcome.ok
    assert actions == [
        "switch:qq",
        "home",
        "wait_any:pause_collection/play_collection",
        "wait_clickable:collection_title",
        "wait:collection_topic",
        "attr:content-desc",
        "click:play_collection",
        "queue",
    ]
    # 房名取队列第一首歌的歌名，话题取裁剪后的电台名。
    assert outcome.title == "新歌"
    assert outcome.topic == "每周甄选"
    assert outcome.playlist == "每周甄选"
    assert outcome.extra["playlist"] == "新歌 - 歌手甲\n老歌 - 歌手乙"


def test_collection_refreshes_the_recommendation_when_it_is_old(music_manager):
    actions = []
    music_manager.music_handler.config = _filter_config()
    lookup = _ReleaseLookup({"老歌": "1995-03-01", "新歌": "2021-05-01"})
    music_manager._song_release_lookup = lookup
    elements = _collection_elements(actions, texts=["老歌 - 歌手丙", "新歌 - 歌手甲"])
    driver, _ = _driver(
        elements, actions, setup=_collection_setup(), queue="新歌 - 歌手甲"
    )

    outcome = driver.start_playback(_radio("collection"))

    assert outcome.ok
    # 换过一次推荐：先回首页再认一次播放按钮。
    assert actions.count("click:home_nav") == 1
    assert actions.count("wait_clickable:home_nav") == 1
    assert actions[-2:] == ["click:play_collection", "queue"]
    assert lookup.queries == ["老歌", "新歌"], "老歌判定要走统一的发行日期查询"


def test_collection_stops_refreshing_once_the_budget_is_spent(music_manager):
    actions = []
    music_manager.music_handler.config = _filter_config(radio_max_refreshes=2)
    music_manager._song_release_lookup = _ReleaseLookup({"老歌": "1995-03-01"})
    elements = _collection_elements(actions, texts=["老歌 - 歌手丙"] * 4)
    driver, _ = _driver(
        elements, actions, setup=_collection_setup(), queue="老歌 - 歌手丙"
    )

    outcome = driver.start_playback(_radio("collection"))

    # 全是老歌也不能一直换下去 —— 换满预算就照播，否则房间永远开不了台。
    assert outcome.ok
    assert actions.count("click:home_nav") == 2
    assert actions.count("click:play_collection") == 1


def test_collection_honours_the_configured_refresh_budget(music_manager):
    actions = []
    music_manager.music_handler.config = _filter_config(radio_max_refreshes=0)
    music_manager._song_release_lookup = _ReleaseLookup({"老歌": "1995-03-01"})
    driver, _ = _driver(
        _collection_elements(actions, texts=["老歌 - 歌手丙"] * 2), actions,
        setup=_collection_setup(),
    )

    outcome = driver.start_playback(_radio("collection"))

    assert outcome.ok
    assert actions.count("click:home_nav") == 0
    assert actions.count("click:play_collection") == 1


def test_collection_re_reads_a_stale_recommendation_element(music_manager):
    """频道自己刷新了卡片：元素失效要重新找，而不是让整条电台失败。"""
    actions = []
    music_manager.music_handler.config = _filter_config()
    music_manager._song_release_lookup = _ReleaseLookup({"新歌": "2021-05-01"})
    driver, _ = _driver(
        _collection_elements(actions, stale_reads=1), actions,
        setup=_collection_setup(), queue="新歌 - 歌手甲",
    )

    outcome = driver.start_playback(_radio("collection"))

    assert outcome.ok
    assert actions.count("wait:collection_topic") == 2


def test_collection_reads_the_station_name_from_the_qq_music_handler(music_manager):
    """控件在 QQ Music 屏幕上，就该问 QQ Music 的 finder —— 迁移前借的是 Soul 的。"""
    actions = []
    music_manager.music_handler.config = _filter_config()
    music_manager._song_release_lookup = _ReleaseLookup({"新歌": "2021-05-01"})
    driver, handler = _driver(
        _collection_elements(actions), actions, setup=_collection_setup(),
        queue="新歌 - 歌手甲",
    )

    outcome = driver.start_playback(_radio("collection"))

    assert handler.element_finder.attrs_seen == ["content-desc"]
    assert outcome.playlist == "每周甄选"


def test_radio_subtitles_keep_their_own_hyphen_convention(music_manager):
    """电台卡片副标题按裸 `-` 拆，与队列行的 `" - "` 约定刻意不同。

    `Lo-Fi` 里的裸连字符是歌名的一部分：在队列行约定下它必须原样保留，在电台
    副标题约定下它却是「题材 - 年代」的分隔符。两套约定各有道理，
    `PlaylistAdoption.primary_topic` 的 docstring 也警告过别混用，因此这里
    钉住电台自己的拆法，防止有人顺手「统一」成那一个。
    """
    actions = []
    driver, _ = _driver(
        {
            "guess_title": _FakeElement("guess_title", "每日猜你喜欢", actions),
            "guess_topic": _FakeElement("guess_topic", "Lo-Fi 夜行", actions),
        },
        actions,
        queue="Lo-Fi 夜行 - 歌手甲",
    )

    outcome = driver.start_playback(_radio("guess"))

    assert outcome.topic == "Lo"
    assert outcome.topic != primary_topic("Lo-Fi 夜行")
    assert primary_topic(outcome.extra["playlist"]) == "Lo-Fi 夜行"


def test_collection_leaves_the_home_page_when_the_station_is_already_playing(
    music_manager,
):
    """频道正在播「精选」时，点开卡片不会换歌 —— 必须先回首页让它换。"""
    actions = []
    music_manager.music_handler.config = _filter_config()
    music_manager._song_release_lookup = _ReleaseLookup({"新歌": "2021-05-01"})
    driver, _ = _driver(
        _collection_elements(actions, playing=True), actions,
        setup=_collection_setup(playing=True), queue="新歌 - 歌手甲",
    )

    outcome = driver.start_playback(_radio("collection"))

    assert outcome.ok
    assert actions[:5] == [
        "switch:qq",
        "home",
        "wait_any:pause_collection/play_collection",
        "wait_clickable:home_nav",
        "click:home_nav",
    ]
    assert actions[-2:] == ["click:play_collection", "queue"]


# ---------------------------------------------------------------------------
# Slice 4: 守护拒绝时，一个 UI 动作、一次麦克风动作都不该发生
# ---------------------------------------------------------------------------


async def test_guarded_radio_touches_neither_the_ui_nor_the_microphone(radio_engine):
    """被歌单守护拒绝的 `:radio` 必须干净中止。

    麦克风日记为空是这条验收标准的要害：命令级 `playback_muting = True` 会在守护
    **之前**就闭麦，于是被拒绝的切歌也会在房间里响一次无来由的静音。守护与闭麦
    都收进引擎之后，拒绝就是拒绝 —— 什么都不发生。
    """
    radio_engine.info.protection_error = "歌单正在被 XXX 播放中"

    command = RadioCommand(_controller())
    result = await command.do_process(
        MessageInfo(content="/radio daily", nickname="小明"), ["daily"]
    )

    assert "error" in result
    assert radio_engine.driver.requests == [], "守护拒绝时不该发出任何播放请求"
    assert radio_engine.journal == [], "守护拒绝时不该有任何 UI 动作或麦克风动作"


async def test_allowed_radio_mutes_only_around_the_track_change(radio_engine):
    """守护放行才轮到引擎按切歌边界接管麦克风（ADR-0007）。"""
    command = RadioCommand(_controller())

    result = await command.do_process(
        MessageInfo(content="/radio collection", nickname="小明"), ["collection"]
    )

    assert "error" not in result
    assert radio_engine.journal == ["mute", "ui:radio", "restore"]
    # 房间采纳的是驱动观察到的事实，不是命令层手拼的。
    assert radio_engine.info.player_name == "小明"
    assert radio_engine.info.current_playlist_name == "每日猜你喜欢"
    assert radio_engine.room_profile.titles == ["每日猜你喜欢"]
    assert radio_engine.room_profile.topics == ["新歌"]
    assert result["playlist"] == "每日猜你喜欢"


def test_collection_accepts_a_recommendation_with_no_release_date(music_manager):
    """查不到发行日期就照播 —— 宁可放一首查不到年代的歌，也不要让房间开不了台。"""
    actions = []
    music_manager.music_handler.config = _filter_config()
    music_manager._song_release_lookup = _ReleaseLookup({})
    driver, _ = _driver(
        _collection_elements(actions, texts=["未知歌 - 歌手甲"]), actions,
        setup=_collection_setup(), queue="未知歌 - 歌手甲",
    )

    outcome = driver.start_playback(_radio("collection"))

    assert outcome.ok
    assert actions.count("click:home_nav") == 0
    assert actions.count("click:play_collection") == 1
