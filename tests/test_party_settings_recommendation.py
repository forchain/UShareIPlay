"""派对设置面板驱动与 `:recommend` 的离线测试（#456 / #457）。

Soul 把「推荐分发」从房间信息抽屉搬到了派对设置面板。本文件考的是这块新屏幕
上的整条纵切：

- 端口只建模物理动作：开面板、带上限翻页找状态项、点状态项、点选项、关面板；
  读文本的判定仍走 handler 的 element_finder。
- `RoomProfileManager` 拥有「谁开谁关」「同态跳过点击」「失败也要收尾」这些决策。
- `:recommend` 只是一层参数解析与回复适配器。
- 生产适配器在真实 handler 形状上的映射（ivClose 关不掉时用返回键兜底）。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.commands.recommend import RecommendCommand
from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.managers.room_profile import party_settings as party_settings_module
from ushareiplay.managers.room_profile import manager as manager_module
from ushareiplay.managers.room_profile.party_settings import (
    DEFAULT_MAX_SWIPES,
    PARTY_SETTING_BUTTON_KEY,
    PARTY_SETTING_CLOSE_KEY,
    PARTY_SETTING_TITLE_KEY,
    RECOMMENDATION_OPTION_KEYS,
    RECOMMENDATION_SHEET_KEY,
    RECOMMENDATION_STATUS_KEY,
    PartySettingsDriverPort,
    SoulPartySettingsDriver,
)
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_party_settings_driver import (
    CLOSED_TEXT,
    OPEN_TEXT,
    InMemoryPartySettingsDriver,
)

CONFIG = {'elements': {'party_setting_button': 'cn.soulapp.android:id/partySettingBtn'}}


@pytest.fixture(autouse=True)
def reset_singletons():
    for cls in (RoomProfileManager, RoomState):
        cls.reset_instance()
    yield
    for cls in (RoomProfileManager, RoomState):
        cls.reset_instance()


# --------------------------------------------------------------------------
# 离线替身：handler 只负责「读文本」，物理动作全在端口后
# --------------------------------------------------------------------------


class _Element:
    def __init__(self, text=''):
        self.text = text

    def click(self):
        return None


class _StatusFinder:
    """只认推荐状态那一行；文本跟着内存驱动的 `status_text` 走。"""

    def __init__(self, driver):
        self.driver = driver

    def try_find_element(self, key, log=False):
        if key == RECOMMENDATION_STATUS_KEY and self.driver.status_visible:
            return _Element(self.driver.status_text)
        return None

    def wait_for_element(self, key, timeout=10):
        return self.try_find_element(key)

    def wait_for_element_clickable(self, key, timeout=10):
        return self.try_find_element(key)

    def get_element_text(self, element):
        return getattr(element, 'text', '')


class _Handler:
    def __init__(self, driver):
        self.logger = MagicMock()
        self.key_actions = SimpleNamespace(
            switch_to_app=lambda: True, press_back=lambda: None
        )
        self.element_finder = _StatusFinder(driver)
        self.config = CONFIG


def _profile(driver=None, handler=None):
    handler = handler or _Handler(driver)
    return RoomProfileManager.initialize(
        handler=handler, settings_driver=driver
    )


def _driver(**kwargs):
    return InMemoryPartySettingsDriver(**kwargs)


# --------------------------------------------------------------------------
# set_recommendation：设置面板的完整生命周期
# --------------------------------------------------------------------------


def test_set_recommendation_turns_off_through_the_settings_panel():
    driver = _driver(status_text=OPEN_TEXT)
    profile = _profile(driver)
    room_state = RoomState.initialize()

    result = profile.set_recommendation(False)

    assert result == {'success': True, 'recommendation_enabled': False}
    assert room_state.recommendation_enabled is False
    assert driver.opened == 1
    assert driver.clicks == [RECOMMENDATION_STATUS_KEY, RECOMMENDATION_OPTION_KEYS[False]]
    assert driver.close_calls == 1
    assert driver.is_open() is False, '自己打开的面板必须自己关'


def test_set_recommendation_turns_on_through_the_settings_panel():
    driver = _driver(status_text=CLOSED_TEXT)
    profile = _profile(driver)
    room_state = RoomState.initialize()

    result = profile.set_recommendation(True)

    assert result == {'success': True, 'recommendation_enabled': True}
    assert room_state.recommendation_enabled is True
    assert driver.option_clicks == [True]
    assert driver.is_open() is False


def test_the_target_state_skips_the_second_level_popup():
    """已经是目标状态就不要再点一次：不点状态项，也不点选项。"""
    driver = _driver(status_text=OPEN_TEXT)
    profile = _profile(driver)
    room_state = RoomState.initialize()

    result = profile.set_recommendation(True)

    assert result == {'success': True, 'recommendation_enabled': True}
    assert driver.clicks == []
    assert driver.option_clicks == []
    assert room_state.recommendation_enabled is True
    assert driver.close_calls == 1


def test_a_panel_someone_else_opened_is_not_closed_by_the_manager():
    driver = _driver(panel_open=True, status_text=OPEN_TEXT)
    profile = _profile(driver)
    RoomState.initialize()

    result = profile.set_recommendation(False)

    assert result == {'success': True, 'recommendation_enabled': False}
    assert driver.open_attempts == 0, '已经开着就不要再点设置按钮'
    assert driver.close_calls == 0, '面板是外层开的，就由外层关'
    assert driver.is_open() is True


def test_the_settings_panel_is_found_after_scrolling():
    driver = _driver(status_text=OPEN_TEXT, visible_after_swipes=3)
    profile = _profile(driver)
    RoomState.initialize()

    assert profile.set_recommendation(False) == {
        'success': True,
        'recommendation_enabled': False,
    }
    assert driver.swipes == 3
    assert driver.swipe_limits == [DEFAULT_MAX_SWIPES]


def test_a_guest_room_refuses_to_touch_the_settings_panel():
    driver = _driver()
    profile = _profile(driver)
    RoomState.initialize().is_guest_room = True

    result = profile.set_recommendation(False)

    assert result == {'error': '他人房间模式下不可修改推荐状态'}
    assert driver.open_attempts == 0
    assert driver.clicks == []


def test_a_missing_settings_driver_is_reported_as_an_error():
    profile = RoomProfileManager.initialize(handler=_Handler(_driver()))
    RoomState.initialize()

    assert profile.set_recommendation(True) == {'error': '派对设置面板不可用'}


def test_a_panel_that_never_opens_is_reported_without_a_blind_close():
    driver = _driver(fail_open=True)
    profile = _profile(driver)

    result = profile.set_recommendation(False)

    assert result == {'error': '无法打开派对设置面板'}
    assert driver.close_calls == 0, '根本没打开过，就不该声称自己关了'


def test_a_scroll_that_never_finds_the_status_closes_the_panel():
    driver = _driver(visible_after_swipes=99, fail_scroll=True)
    profile = _profile(driver)
    RoomState.initialize()

    result = profile.set_recommendation(False)

    assert result == {'error': '未找到推荐状态设置项'}
    assert driver.close_calls == 1
    assert driver.is_open() is False


def test_an_unrecognized_status_text_is_an_error_and_still_closes():
    driver = _driver(status_text='未知文案')
    profile = _profile(driver)

    result = profile.set_recommendation(False)

    assert result == {'error': '无法读取推荐状态'}
    assert driver.clicks == []
    assert driver.close_calls == 1


def test_a_status_entry_that_cannot_be_clicked_closes_the_panel():
    driver = _driver(fail_status_click=True)
    profile = _profile(driver)

    result = profile.set_recommendation(False)

    assert result == {'error': '无法点击推荐状态设置项'}
    assert driver.close_calls == 1
    assert driver.is_open() is False


def test_an_option_that_cannot_be_clicked_keeps_the_old_state():
    driver = _driver(status_text=OPEN_TEXT, fail_option=True)
    profile = _profile(driver)
    room_state = RoomState.initialize()

    result = profile.set_recommendation(False)

    assert result == {'error': '未找到推荐选项'}
    assert room_state.recommendation_enabled is None, '没点成功就不许记账'
    assert driver.close_calls == 1


# --------------------------------------------------------------------------
# inspect_current_ui_status：只读探测
# --------------------------------------------------------------------------


def test_inspection_reads_the_status_and_syncs_room_state():
    driver = _driver(status_text=CLOSED_TEXT)
    profile = _profile(driver)
    room_state = RoomState.initialize()

    assert profile.inspect_current_ui_status() is False
    assert room_state.recommendation_enabled is False
    assert driver.opened == 1
    assert driver.close_calls == 1
    assert driver.clicks == []


def test_inspection_without_a_driver_returns_none():
    profile = RoomProfileManager.initialize(handler=_Handler(_driver()))

    assert profile.inspect_current_ui_status() is None


def test_inspection_does_not_run_in_a_guest_room():
    driver = _driver()
    profile = _profile(driver)
    RoomState.initialize().is_guest_room = True

    assert profile.inspect_current_ui_status() is None
    assert driver.open_attempts == 0


# --------------------------------------------------------------------------
# 回房接地：只在推荐状态未知时问一次设置面板
# --------------------------------------------------------------------------


def test_grounding_probes_the_settings_panel_while_the_state_is_unknown():
    driver = _driver(status_text=CLOSED_TEXT)
    profile = _profile(driver)
    room_state = RoomState.initialize()

    result = profile.ensure_synced_on_return()

    assert driver.opened == 1
    assert room_state.recommendation_enabled is False
    assert result.get('skipped') is not True, '房名读不到不改变推荐探测发生过'


def test_grounding_skips_the_settings_panel_once_the_state_is_known():
    driver = _driver(status_text=CLOSED_TEXT)
    profile = _profile(driver)
    RoomState.initialize().recommendation_enabled = True
    profile.is_initialized = True

    assert profile.ensure_synced_on_return() == {
        'skipped': True,
        'reason': 'already_initialized',
    }
    assert driver.open_attempts == 0


# --------------------------------------------------------------------------
# `:recommend` 命令层
# --------------------------------------------------------------------------


class _Runtime:
    def __init__(self, handler):
        self.soul_handler = handler
        self.music_handler = SimpleNamespace()


def _command(driver):
    handler = _Handler(driver)
    _profile(driver, handler)
    return RecommendCommand(_Runtime(handler))


@pytest.mark.asyncio
async def test_recommend_without_arguments_toggles_an_open_panel_off():
    driver = _driver(status_text=OPEN_TEXT)
    RoomState.initialize().recommendation_enabled = True
    cmd = _command(driver)

    result = await cmd.do_process(SimpleNamespace(nickname='Console'), [])

    assert result == {'status': '关闭'}
    assert driver.option_clicks == [False]
    assert RoomState.instance().recommendation_enabled is False


@pytest.mark.asyncio
async def test_recommend_without_arguments_toggles_a_closed_panel_on():
    driver = _driver(status_text=CLOSED_TEXT)
    RoomState.initialize().recommendation_enabled = False
    cmd = _command(driver)

    result = await cmd.do_process(SimpleNamespace(nickname='Console'), [])

    assert result == {'status': '开放'}
    assert driver.option_clicks == [True]


@pytest.mark.asyncio
async def test_recommend_without_arguments_enables_when_the_state_is_unknown():
    driver = _driver(status_text=CLOSED_TEXT)
    RoomState.initialize()
    cmd = _command(driver)

    result = await cmd.do_process(SimpleNamespace(nickname='Console'), [])

    assert result == {'status': '开放'}
    assert driver.option_clicks == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'argument, expected_status, expected_option',
    [
        ('on', '开放', True),
        ('open', '开放', True),
        ('1', '开放', True),
        ('开启', '开放', True),
        ('开放', '开放', True),
        ('所有人', '开放', True),
        ('off', '关闭', False),
        ('close', '关闭', False),
        ('0', '关闭', False),
        ('关闭', '关闭', False),
        ('关闭推荐分发', '关闭', False),
    ],
)
async def test_recommend_accepts_the_documented_aliases(
    argument, expected_status, expected_option
):
    driver = _driver(
        status_text=CLOSED_TEXT if expected_option else OPEN_TEXT
    )
    RoomState.initialize().recommendation_enabled = not expected_option
    cmd = _command(driver)

    result = await cmd.do_process(SimpleNamespace(nickname='Console'), [argument])

    assert result == {'status': expected_status}
    assert driver.option_clicks == [expected_option]


@pytest.mark.asyncio
async def test_recommend_rejects_an_unknown_argument_without_touching_the_panel():
    driver = _driver()
    RoomState.initialize()
    cmd = _command(driver)

    result = await cmd.do_process(SimpleNamespace(nickname='Console'), ['maybe'])

    assert 'error' in result
    assert '未知参数' in result['error']
    assert driver.open_attempts == 0


@pytest.mark.asyncio
async def test_recommend_propagates_a_manager_error():
    driver = _driver(visible_after_swipes=99, fail_scroll=True)
    RoomState.initialize()
    cmd = _command(driver)

    result = await cmd.do_process(SimpleNamespace(nickname='Console'), ['off'])

    assert result == {'error': '未找到推荐状态设置项'}


@pytest.mark.asyncio
async def test_recommend_does_not_touch_the_panel_when_soul_cannot_be_switched_to():
    driver = _driver()
    RoomState.initialize()
    handler = _Handler(driver)
    handler.key_actions = SimpleNamespace(
        switch_to_app=lambda: False, press_back=lambda: None
    )
    _profile(driver, handler)
    cmd = RecommendCommand(_Runtime(handler))

    assert await cmd.do_process(SimpleNamespace(nickname='Console'), []) == {
        'error': 'Failed to switch to Soul app'
    }
    assert driver.open_attempts == 0


# --------------------------------------------------------------------------
# 生产适配器：真实 handler 形状上的映射
# --------------------------------------------------------------------------


class _ProdElement:
    def __init__(self, key, text='', displayed=True, panel=None, finder=None):
        self.key = key
        self.text = text
        self.displayed = displayed
        self.size = {'width': 100, 'height': 40}
        self.location = {'x': 0, 'y': 0}
        self.clicks = 0
        self.panel = panel
        self.finder = finder

    def is_displayed(self):
        return self.displayed

    def click(self):
        self.clicks += 1
        if self.panel is not None and self.finder is not None:
            if self.key == PARTY_SETTING_BUTTON_KEY:
                self.panel['open'] = True
                self.finder.elements[PARTY_SETTING_TITLE_KEY] = _ProdElement(
                    PARTY_SETTING_TITLE_KEY, panel=self.panel, finder=self.finder
                )
            if self.key == PARTY_SETTING_CLOSE_KEY and self.panel.get('close_works', True):
                self.panel['open'] = False
                for key in (PARTY_SETTING_TITLE_KEY, PARTY_SETTING_CLOSE_KEY):
                    self.finder.elements.pop(key, None)


class _ProdFinder:
    def __init__(self, elements):
        self.elements = elements

    def try_find_element(self, key, log=False):
        return self.elements.get(key)

    def wait_for_element(self, key, timeout=10):
        return self.elements.get(key)

    def wait_for_element_clickable(self, key, timeout=10):
        return self.elements.get(key)

    def wait_for_any_element(self, keys, timeout=10):
        for key in keys:
            if key in self.elements:
                return key, self.elements[key]
        return None, None

    def wait_for_element_disappear(self, key, timeout=3.0, poll_frequency=0.1):
        return key not in self.elements


class _ProdGesture:
    def __init__(self, finder, panel):
        self.finder = finder
        self.panel = panel
        self.clicks = []
        self.scrolls = []

    def click_element_at(self, element):
        self.clicks.append(element.key)
        return True

    def swipe_until_element(
        self, element_key, direction='up', max_swipes=10
    ):
        self.scrolls.append((element_key, direction, max_swipes))
        return self.finder.elements.get(element_key)

    def scroll_container_until_element(
        self, element_key, container_key, direction='up', max_swipes=10
    ):
        self.scrolls.append((element_key, container_key, direction, max_swipes))
        return element_key, self.finder.elements.get(element_key), []


class _ProdHandler:
    def __init__(self, elements=None, panel=None):
        self.panel = panel if panel is not None else {'open': False}
        elements_dict = dict(elements or {})
        for el in elements_dict.values():
            el.panel = self.panel
        self.element_finder = _ProdFinder(elements_dict)
        for el in elements_dict.values():
            el.finder = self.element_finder
        self.gesture_handler = _ProdGesture(self.element_finder, self.panel)
        self.key_actions = SimpleNamespace(
            press_back=self._press_back, switch_to_app=lambda: True
        )
        self.back_presses = 0
        self.logger = MagicMock()

    def _press_back(self):
        self.back_presses += 1
        self.panel['open'] = False
        for key in (PARTY_SETTING_TITLE_KEY, PARTY_SETTING_CLOSE_KEY):
            self.element_finder.elements.pop(key, None)


def test_an_exception_from_the_driver_becomes_a_user_facing_error():
    class _ExplodingDriver(InMemoryPartySettingsDriver):
        def is_open(self):
            raise RuntimeError('appium is gone')

    profile = _profile(_ExplodingDriver())
    RoomState.initialize()

    assert profile.set_recommendation(True) == {'error': '设置推荐状态时出错'}


def test_the_settings_port_is_an_abstract_boundary():
    with pytest.raises(TypeError):
        PartySettingsDriverPort()

    assert isinstance(
        InMemoryPartySettingsDriver(), PartySettingsDriverPort
    ), '内存替身必须走真实端口，否则 ABC 的约束形同虚设'


def test_the_production_driver_opens_the_panel_with_the_setting_button():
    btn = _ProdElement(PARTY_SETTING_BUTTON_KEY)
    handler = _ProdHandler(elements={PARTY_SETTING_BUTTON_KEY: btn})
    driver = SoulPartySettingsDriver(handler)

    assert driver.is_open() is False
    assert driver.open() is True
    assert btn.clicks == 1
    assert driver.is_open() is True


def test_the_production_driver_uses_the_scroll_helper_with_the_swipe_limit():
    status = _ProdElement(RECOMMENDATION_STATUS_KEY, text=OPEN_TEXT)
    handler = _ProdHandler()  # 状态项一开始不在屏幕上
    driver = SoulPartySettingsDriver(handler)

    original = handler.gesture_handler.swipe_until_element

    def scroll_and_reveal(element_key, direction='up', max_swipes=10):
        original(element_key, direction, max_swipes)
        return status

    handler.gesture_handler.swipe_until_element = scroll_and_reveal

    assert driver.reveal_recommendation_status(max_swipes=3) is True
    assert handler.gesture_handler.scrolls == [
        (RECOMMENDATION_STATUS_KEY, 'up', 3)
    ]


def test_the_production_driver_does_not_scroll_when_the_status_is_visible():
    status = _ProdElement(RECOMMENDATION_STATUS_KEY, text=OPEN_TEXT)
    handler = _ProdHandler(elements={RECOMMENDATION_STATUS_KEY: status})
    driver = SoulPartySettingsDriver(handler)

    assert driver.reveal_recommendation_status() is True
    assert handler.gesture_handler.scrolls == []


def test_the_production_driver_closes_with_ivclose():
    close_btn = _ProdElement(PARTY_SETTING_CLOSE_KEY)
    handler = _ProdHandler(
        elements={
            PARTY_SETTING_TITLE_KEY: _ProdElement(PARTY_SETTING_TITLE_KEY),
            PARTY_SETTING_CLOSE_KEY: close_btn,
        }
    )
    handler.panel['open'] = True
    driver = SoulPartySettingsDriver(handler)

    driver.close()

    assert close_btn.clicks == 1
    assert handler.back_presses == 0
    assert driver.is_open() is False


def test_the_production_driver_falls_back_to_back_when_ivclose_does_not_close():
    handler = _ProdHandler(
        elements={
            PARTY_SETTING_TITLE_KEY: _ProdElement(PARTY_SETTING_TITLE_KEY),
            PARTY_SETTING_CLOSE_KEY: _ProdElement(PARTY_SETTING_CLOSE_KEY),
        }
    )
    handler.panel['open'] = True
    handler.panel['close_works'] = False
    driver = SoulPartySettingsDriver(handler)

    driver.close()

    assert handler.back_presses == 1, 'ivClose 关不掉时按一次返回兜底'
    assert driver.is_open() is False


def test_the_production_driver_maps_the_target_state_to_the_option_key():
    option_open = _ProdElement(RECOMMENDATION_OPTION_KEYS[True])
    option_close = _ProdElement(RECOMMENDATION_OPTION_KEYS[False])
    handler = _ProdHandler(
        elements={
            RECOMMENDATION_OPTION_KEYS[True]: option_open,
            RECOMMENDATION_OPTION_KEYS[False]: option_close,
        }
    )
    driver = SoulPartySettingsDriver(handler)

    assert driver.click_recommendation_option(True) is True
    assert option_open.clicks == 1
    assert driver.click_recommendation_option(False) is True
    assert option_close.clicks == 1


def test_the_production_driver_reports_a_missing_option_as_false():
    driver = SoulPartySettingsDriver(_ProdHandler())

    assert driver.click_recommendation_option(True) is False


def test_the_production_driver_fails_when_handler_missing():
    """handler 缺失时应直接报错（fail-fast），严禁过度防御静默吞异常。"""
    driver = SoulPartySettingsDriver(None)

    with pytest.raises(AttributeError):
        driver.is_open()


# --------------------------------------------------------------------------
# 回归：面板还在惯性滑动时的状态行点击
#
# 真机症状：`:recommend off` 报「未找到推荐选项」。翻页找状态项的那一滑还带着
# 惯性，状态行会继续往上飘，这时候点下去被 ScrollView 吃掉 —— 二级弹窗根本没开，
# 选项自然找不到（真机证据：点前 [525,549][603,586]，1.5 秒后 [525,532][603,569]）。
# --------------------------------------------------------------------------


class _FakeClock:
    """假时钟：只有 sleep 会推进时间。"""

    def __init__(self):
        self.slept = 0.0

    def sleep(self, seconds):
        self.slept += seconds

    def time(self):
        return self.slept


class _FakeElement:
    """只会显示、能被点的假元素。"""

    def __init__(self, text=''):
        self.text = text
        self.clicks = 0
        self.displayed = True

    def is_displayed(self):
        return self.displayed

    def click(self):
        self.clicks += 1


class _MovingStatusElement(_FakeElement):
    """点击时还在往上飘的状态行：模拟 ScrollView 的惯性滑动。

    前 `moves` 次读 rect 每次都在变，之后稳定 —— 真机上就是这个样子。
    """

    def __init__(self, finder, *, moves=2):
        super().__init__()
        self.finder = finder
        self.moves = moves
        self.reads = 0
        self.rect_at_click = None
        self._rect = {'x': 0, 'y': 100}

    @property
    def rect(self):
        self.reads += 1
        if self.reads <= self.moves:
            self._rect = {'x': 0, 'y': 100 - self.reads * 17}
        return self._rect

    def click(self):
        super().click()
        self.rect_at_click = dict(self.rect)
        self.finder.status_clicks += 1
        if self.finder.status_clicks >= self.finder.sheet_opens_on_click:
            self.finder.sheet_open = True


class _SheetButtonElement(_FakeElement):
    def __init__(self, finder):
        super().__init__()
        self.finder = finder

    def click(self):
        super().click()
        self.finder.panel_open = True


class _SheetFinder:
    """原生面板 + 二级弹窗的替身 finder。"""

    def __init__(self, *, sheet_opens_on_click=1, status_element=None):
        self.sheet_opens_on_click = sheet_opens_on_click
        self.status_element = status_element
        self.sheet_open = False
        self.panel_open = False
        self.status_clicks = 0
        self.button = _SheetButtonElement(self)
        self.close_button = _FakeElement()
        self.disappeared = []

    def try_find_element(self, key, log=False):
        if key == RECOMMENDATION_SHEET_KEY:
            return _FakeElement() if self.sheet_open else None
        if key == PARTY_SETTING_TITLE_KEY:
            return _FakeElement() if self.panel_open else None
        if key == RECOMMENDATION_STATUS_KEY:
            return self.status_element
        if key == PARTY_SETTING_BUTTON_KEY:
            return self.button
        if key == PARTY_SETTING_CLOSE_KEY:
            return self.close_button
        if key in RECOMMENDATION_OPTION_KEYS.values():
            return _FakeElement() if self.sheet_open else None
        return None

    def wait_for_element(self, key, timeout=10):
        return self.try_find_element(key)

    def wait_for_element_clickable(self, key, timeout=10):
        return self.try_find_element(key)

    def wait_for_element_disappear(self, key, timeout=3.0, poll_frequency=0.1):
        self.disappeared.append(key)
        if key == PARTY_SETTING_TITLE_KEY:
            self.panel_open = False
        if key == RECOMMENDATION_SHEET_KEY:
            self.sheet_open = False
        return True


class _SheetHandler:
    def __init__(self, finder):
        self.element_finder = finder
        self.key_actions = SimpleNamespace(press_back=self._press_back)
        self.logger = MagicMock()
        self.back_presses = 0

    def _press_back(self):
        self.back_presses += 1
        self.element_finder.sheet_open = False


def _sheet_driver(monkeypatch, finder):
    """带假时钟的生产驱动：settle 等待不真的睡。"""
    monkeypatch.setattr(party_settings_module, 'time', _FakeClock())
    return SoulPartySettingsDriver(_SheetHandler(finder))


def test_the_status_click_waits_until_the_row_stops_moving(monkeypatch):
    finder = _SheetFinder()
    status = _MovingStatusElement(finder, moves=2)
    finder.status_element = status
    driver = _sheet_driver(monkeypatch, finder)

    assert driver.click_recommendation_status() is True
    assert status.clicks == 1
    assert status.rect_at_click == {'x': 0, 'y': 100 - 2 * 17}, (
        '行还在飘就点下去会被滚动容器吃掉 —— 弹窗不开，选项也就永远找不到'
    )


def test_the_status_click_is_retried_when_the_sheet_does_not_open(monkeypatch):
    finder = _SheetFinder(sheet_opens_on_click=2)
    status = _MovingStatusElement(finder, moves=0)
    finder.status_element = status
    driver = _sheet_driver(monkeypatch, finder)

    assert driver.click_recommendation_status() is True
    assert status.clicks == 2, '第一次点击被吃掉时要再点一次'


def test_the_status_click_gives_up_after_the_retry_budget(monkeypatch):
    finder = _SheetFinder(sheet_opens_on_click=99)
    status = _MovingStatusElement(finder, moves=0)
    finder.status_element = status
    driver = _sheet_driver(monkeypatch, finder)

    assert driver.click_recommendation_status() is False
    assert status.clicks == party_settings_module.STATUS_CLICK_ATTEMPTS


def test_a_leftover_option_sheet_is_dismissed_before_the_panel_is_opened(monkeypatch):
    finder = _SheetFinder()
    finder.sheet_open = True
    handler = _SheetHandler(finder)
    monkeypatch.setattr(party_settings_module, 'time', _FakeClock())
    driver = SoulPartySettingsDriver(handler)

    assert driver.open() is True
    assert handler.back_presses == 1, '残留的二级弹窗会把设置按钮整个盖住'
    assert finder.button.clicks == 1


def test_closing_the_panel_also_dismisses_a_leftover_option_sheet(monkeypatch):
    finder = _SheetFinder()
    finder.panel_open = True
    finder.sheet_open = True
    handler = _SheetHandler(finder)
    monkeypatch.setattr(party_settings_module, 'time', _FakeClock())
    driver = SoulPartySettingsDriver(handler)

    driver.close()

    assert handler.back_presses == 1
    assert finder.close_button.clicks == 1, '弹窗按掉之后还要把原生面板关掉'


def test_choosing_an_option_waits_for_the_sheet_to_close(monkeypatch):
    finder = _SheetFinder()
    finder.sheet_open = True
    monkeypatch.setattr(party_settings_module, 'time', _FakeClock())
    driver = SoulPartySettingsDriver(_SheetHandler(finder))

    assert driver.click_recommendation_option(False) is True
    assert RECOMMENDATION_SHEET_KEY in finder.disappeared


class _SilentOptionDriver(InMemoryPartySettingsDriver):
    """选项点下去了，但面板那一行没变 —— 「点了就当成了」的典型。"""

    def click_recommendation_option(self, enabled: bool) -> bool:
        self.option_clicks.append(bool(enabled))
        return True


def test_the_recommendation_is_only_reported_as_set_when_the_ui_really_changed(
    monkeypatch,
):
    monkeypatch.setattr(manager_module, 'RECOMMENDATION_SETTLE_TIMEOUT', 0.05)
    monkeypatch.setattr(manager_module, 'RECOMMENDATION_SETTLE_POLL', 0.01)
    driver = _SilentOptionDriver(status_text=OPEN_TEXT)
    profile = _profile(driver)
    room_state = RoomState.initialize()

    result = profile.set_recommendation(False)

    assert result == {'error': '推荐状态未生效'}
    assert room_state.recommendation_enabled is None, '面板那一行没变就不许记账'
    assert driver.close_calls == 1


def test_the_verified_state_is_what_gets_recorded(monkeypatch):
    monkeypatch.setattr(manager_module, 'RECOMMENDATION_SETTLE_TIMEOUT', 0.05)
    monkeypatch.setattr(manager_module, 'RECOMMENDATION_SETTLE_POLL', 0.01)
    driver = _driver(status_text=OPEN_TEXT)
    profile = _profile(driver)
    room_state = RoomState.initialize()

    result = profile.set_recommendation(False)

    assert result == {'success': True, 'recommendation_enabled': False}
    assert room_state.recommendation_enabled is False
