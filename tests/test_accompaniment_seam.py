"""Ticket #427: 伴奏开关收进 MusicManager 播放页接缝的离线测试。

测试面只有三个：`MusicManager.set_accompaniment()`、`AccompanimentCommand.do_process()`，
以及共享的播放页进入仪式在伴奏这条路上的表现。Appium 侧全部由
`tests/fakes/in_memory_music_driver.py` 的脚本化替身顶替，因此 pytest 无需
Android 设备、Appium 服务或真实 `dumpsys` 即可跑完。

「更多」菜单那条滚动通路的断言落在 Slice 4：它靠的是 `ensure_player_page` 的
伴奏探测 key，而不是靠替身 —— 替身只管状态，不知道滚动容器怎么滚。
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ushareiplay.commands.acc import AccompanimentCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.driver import MusicUIDriverPort
from ushareiplay.managers.playback.models import (
    ACCOMPANIMENT_DISABLED_ERROR,
    ACCOMPANIMENT_INVALID_PARAMETER_ERROR,
    NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR,
)
from ushareiplay.managers.playback.player_page import (
    ACCOMPANIMENT_ON_PAGE_KEYS,
    PLAYER_PAGE_PROBE_KEYS,
    ensure_player_page,
)
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_manager(*, driver=None):
    """真实 MusicManager + 内存驱动替身。伴奏状态没有房间缓存，全在替身上。"""
    driver = driver or InMemoryMusicUIDriver()
    manager = MusicManager.initialize(ui_driver=driver)
    return SimpleNamespace(manager=manager, driver=driver)


# ---------------------------------------------------------------------------
# Slice 1: 端口契约
# ---------------------------------------------------------------------------


def test_accompaniment_toggling_is_part_of_the_ui_driver_port_contract():
    """端口又变宽了：少实现 `set_accompaniment` 的适配器装不上。

    这条断言同时是给 #421 生产适配器的提示 —— 三个方法全是抽象方法，
    漏实现会在这里显式炸掉，而不是等到用户敲 `:acc` 才失败。
    """

    class _ModeOnlyDriver(MusicUIDriverPort):
        def start_playback(self, request):
            raise AssertionError("unused")

        def set_play_mode(self, target_mode):
            raise AssertionError("unused")

    with pytest.raises(TypeError):
        _ModeOnlyDriver()


def test_in_memory_driver_satisfies_the_widened_port():
    assert isinstance(InMemoryMusicUIDriver(), MusicUIDriverPort)


# ---------------------------------------------------------------------------
# Slice 2: MusicManager.set_accompaniment
# ---------------------------------------------------------------------------


async def test_set_accompaniment_toggles_the_direct_switch_through_the_driver(
    initialized_test_singletons,
):
    """伴唱页上直接有开关：驱动点一次，状态跟着变，回复形状不变。"""
    engine = _build_manager(driver=InMemoryMusicUIDriver(accompaniment=False))

    result = await engine.manager.set_accompaniment(True)

    assert result == {"enabled": "on"}
    assert engine.driver.accompaniment_requests == [True]
    assert engine.driver.accompaniment_clicks == 1
    assert engine.driver.accompaniment is True


async def test_set_accompaniment_turns_the_direct_switch_off(initialized_test_singletons):
    engine = _build_manager(driver=InMemoryMusicUIDriver(accompaniment=True))

    result = await engine.manager.set_accompaniment(False)

    assert result == {"enabled": "off"}
    assert engine.driver.accompaniment_clicks == 1
    assert engine.driver.accompaniment is False


async def test_set_accompaniment_routes_through_the_more_menu_path(initialized_test_singletons):
    """K歌入口只在「更多」菜单里：驱动器改走滚动容器那条路。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(accompaniment=False, accompaniment_path="more_menu")
    )

    result = await engine.manager.set_accompaniment(True)

    assert result == {"enabled": "on"}
    assert engine.driver.accompaniment_paths == ["more_menu"]
    assert engine.driver.accompaniment_clicks == 1
    assert engine.driver.accompaniment is True


async def test_set_accompaniment_does_nothing_when_already_in_the_target_state(
    initialized_test_singletons,
):
    """本来就是目标状态：一个点击都不该发生，回复仍然成功。"""
    engine = _build_manager(driver=InMemoryMusicUIDriver(accompaniment=True))

    result = await engine.manager.set_accompaniment(True)

    assert result == {"enabled": "on"}
    assert engine.driver.accompaniment_clicks == 0
    assert engine.driver.accompaniment is True


async def test_set_accompaniment_returns_an_error_when_nothing_is_playing(
    initialized_test_singletons,
):
    """没有音乐在放：回用户那句既有文案，而不是让 UI 异常冒到命令层。"""
    engine = _build_manager(driver=InMemoryMusicUIDriver(no_music=True))

    result = await engine.manager.set_accompaniment(True)

    assert result == {"error": NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR}
    assert NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR == (
        "No music playing, cannot toggle accompaniment mode"
    )
    assert engine.driver.accompaniment_clicks == 0


async def test_set_accompaniment_reports_a_collapsed_karaoke_entry(
    initialized_test_singletons,
):
    """K歌入口是灰的：伴奏无从谈起，如实回那句既有文案。"""
    engine = _build_manager(driver=InMemoryMusicUIDriver(accompaniment_disabled=True))

    result = await engine.manager.set_accompaniment(True)

    assert result == {"error": ACCOMPANIMENT_DISABLED_ERROR}
    assert ACCOMPANIMENT_DISABLED_ERROR == "Accompaniment mode is disabled"
    assert engine.driver.accompaniment_clicks == 0


async def test_set_accompaniment_propagates_driver_failures_without_crashing(
    initialized_test_singletons,
):
    """驱动报出的失败原因原样回到命令层。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(
            accompaniment=False, accompaniment_failures={True: "点不动伴奏开关"}
        )
    )

    result = await engine.manager.set_accompaniment(True)

    assert result == {"error": "点不动伴奏开关"}
    assert engine.driver.accompaniment is False


async def test_set_accompaniment_reports_a_switch_that_did_not_take_effect(
    initialized_test_singletons,
):
    """点了但状态没变：按失败回，绝不谎称已开启。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(accompaniment=False, stuck_accompaniment=True)
    )

    result = await engine.manager.set_accompaniment(True)

    assert result["error"] == "FAIL: 伴奏开关点击后状态未变化"
    assert engine.driver.accompaniment is False


async def test_set_accompaniment_accepts_both_index_and_bool_forms(
    initialized_test_singletons,
):
    """1/0 与 True/False 是同一件事的两种写法，端口只收归一后的布尔。"""
    for value, expected in ((1, True), ("1", True), (True, True), (0, False), ("0", False)):
        MusicManager.reset_instance()
        engine = _build_manager()

        result = await engine.manager.set_accompaniment(value)

        assert result == {"enabled": "on" if expected else "off"}
        assert engine.driver.accompaniment_requests == [expected]


async def test_set_accompaniment_rejects_unknown_targets_without_touching_the_ui(
    initialized_test_singletons,
):
    """非法目标当场被拒：不进播放页，也不点任何东西。"""
    for value in ("2", "on", None, 2, -1):
        MusicManager.reset_instance()
        engine = _build_manager()

        result = await engine.manager.set_accompaniment(value)

        assert result == {"error": ACCOMPANIMENT_INVALID_PARAMETER_ERROR}
        assert ACCOMPANIMENT_INVALID_PARAMETER_ERROR == (
            "Invalid accompaniment parameter, must be 1 or 0"
        )
        assert engine.driver.accompaniment_requests == []


async def test_set_accompaniment_without_a_driver_raises_an_assembly_error(
    initialized_test_singletons,
):
    """尚未装配 UI 驱动是装配错误，不能伪装成「切换失败」回复给用户。

    #421 把生产适配器接到组合根之后，这条路径才第一次被真正走到。
    """
    manager = MusicManager.initialize()

    with pytest.raises(RuntimeError, match="MusicUIDriverPort"):
        await manager.set_accompaniment(True)


async def test_set_accompaniment_only_logs_when_a_switch_actually_happened(
    initialized_test_singletons,
):
    """铁律：空转不刷屏。本来就是目标状态时一条日志都不该有。"""
    logs = []

    already_on = _build_manager(driver=InMemoryMusicUIDriver(accompaniment=True))
    already_on.manager.logger = SimpleNamespace(
        info=logs.append, warning=logs.append, error=logs.append
    )
    await already_on.manager.set_accompaniment(True)
    assert logs == []

    MusicManager.reset_instance()
    toggled = _build_manager(driver=InMemoryMusicUIDriver(accompaniment=False))
    toggled.manager.logger = SimpleNamespace(
        info=logs.append, warning=logs.append, error=logs.append
    )
    await toggled.manager.set_accompaniment(True)
    assert len(logs) == 1
    assert "target=on" in logs[0]


# ---------------------------------------------------------------------------
# Slice 3: AccompanimentCommand 只做参数校验与委派
# ---------------------------------------------------------------------------


def _make_command(manager_result=None):
    command = AccompanimentCommand.__new__(AccompanimentCommand)
    command._music_manager = MagicMock()
    command._music_manager.set_accompaniment = AsyncMock(
        return_value=manager_result or {"enabled": "on"}
    )
    return command


async def test_accompaniment_command_requires_a_parameter():
    command = _make_command()

    result = await command.do_process(None, [])

    assert result == {"error": "Missing parameter (on:1, off:0) for accompaniment command"}
    command._music_manager.set_accompaniment.assert_not_awaited()


async def test_accompaniment_command_delegates_the_toggle_to_music_manager():
    """命令层不再有任何 Appium 动作：解析参数后原样返回管理器的回复。"""
    command = _make_command()

    result = await command.do_process(None, ["1"])

    command._music_manager.set_accompaniment.assert_awaited_once_with(True)
    assert result == {"enabled": "on"}
    assert not hasattr(command, "toggle_accompaniment")


async def test_accompaniment_command_keeps_the_zero_off_contract():
    """`:acc 0` 仍是「关」；非 `1` 的参数仍按关处理 —— 解析契约没有变。"""
    command = _make_command({"enabled": "off"})

    result = await command.do_process(None, ["0"])

    command._music_manager.set_accompaniment.assert_awaited_once_with(False)
    assert result == {"enabled": "off"}


async def test_accompaniment_command_returns_the_no_music_error_from_music_manager():
    command = _make_command({"error": NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR})

    result = await command.do_process(None, ["1"])

    command._music_manager.set_accompaniment.assert_awaited_once_with(True)
    assert result == {"error": "No music playing, cannot toggle accompaniment mode"}


def test_accompaniment_command_module_contains_no_ui_automation():
    """命令模块里不该再出现任何 UI 编排的痕迹（#427 的验收条件之一）。"""
    source = (REPO_ROOT / "src" / "ushareiplay" / "commands" / "acc.py").read_text(
        encoding="utf-8"
    )
    for symbol in (
        "element_finder",
        "gesture_handler",
        "wait_for_any_element",
        "scroll_container_until_element",
        "click_element_at",
        "try_find_element",
        "key_actions",
        "accompaniment_text",
        "accompaniment_button",
        "more_entry",
        "playing_bar",
    ):
        assert symbol not in source, f"acc.py 不该再直接引用 {symbol}"


# ---------------------------------------------------------------------------
# Slice 4: 共享的播放页进入仪式（伴奏这条探测路径）
# ---------------------------------------------------------------------------


class _KeyActions:
    def __init__(self, switched=True):
        self.switched = switched
        self.backs = 0

    def switch_to_app(self):
        return self.switched

    def press_back(self):
        self.backs += 1


class _ElementFinder:
    """按脚本依次返回 (key, element)，脚本用尽后返回 (None, None)。"""

    def __init__(self, script=()):
        self.script = list(script)
        self.calls = []

    def wait_for_any_element(self, keys):
        self.calls.append(tuple(keys))
        if not self.script:
            return None, None
        return self.script.pop(0)


class _GestureHandler:
    def __init__(self, clickable=True):
        self.clickable = clickable
        self.clicks = []

    def click_element_at(self, element):
        self.clicks.append(element)
        return self.clickable


class _PlayerHandler:
    def __init__(self, *, switched=True, script=(), clickable=True):
        self.key_actions = _KeyActions(switched)
        self.element_finder = _ElementFinder(script)
        self.gesture_handler = _GestureHandler(clickable)
        self.logger = SimpleNamespace(
            info=lambda msg: None,
            warning=lambda msg: None,
            error=lambda msg: None,
        )


def test_accompaniment_probe_keys_all_come_from_config_yaml():
    """元素选择器的唯一权威是 config.yaml：Python 里只出现 key，不出现 XPath。"""
    config = __import__("yaml").safe_load(
        (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    )
    elements = config["qq_music"]["elements"]

    assert set(ACCOMPANIMENT_ON_PAGE_KEYS) == {
        "accompaniment_text_off",
        "accompaniment_text_on",
        "more_entry",
    }
    assert set(ACCOMPANIMENT_ON_PAGE_KEYS) <= set(elements)
    assert all(not key.startswith("//") for key in ACCOMPANIMENT_ON_PAGE_KEYS)
    # 播放条仍然是「有音乐在放」的通用证据，两条探测路径共用它。
    assert "playing_bar" in PLAYER_PAGE_PROBE_KEYS


def test_ensure_player_page_probes_accompaniment_controls_when_asked():
    """伴奏那条路复用同一段前置动作，只是换掉「站在播放页上」的证据。"""
    toggle = object()
    handler = _PlayerHandler(script=[("accompaniment_text_on", toggle)])

    entry = ensure_player_page(handler, on_page_keys=ACCOMPANIMENT_ON_PAGE_KEYS)

    assert entry.ok is True
    assert entry.element is toggle
    assert handler.gesture_handler.clicks == []
    assert handler.element_finder.calls == [
        ("playing_bar",) + ACCOMPANIMENT_ON_PAGE_KEYS
    ]


def test_ensure_player_page_enters_the_player_page_for_the_more_menu_path():
    """底部有播放条但不在播放页：点进去之后找「更多」入口。"""
    bar = object()
    more_entry = object()
    handler = _PlayerHandler(script=[("playing_bar", bar), ("more_entry", more_entry)])

    entry = ensure_player_page(handler, on_page_keys=ACCOMPANIMENT_ON_PAGE_KEYS)

    assert entry.ok is True
    assert entry.element is more_entry
    assert handler.gesture_handler.clicks == [bar]
    assert handler.key_actions.backs == 1
    assert handler.element_finder.calls == [
        ("playing_bar",) + ACCOMPANIMENT_ON_PAGE_KEYS,
        ACCOMPANIMENT_ON_PAGE_KEYS,
    ]


def test_ensure_player_page_reports_the_accompaniment_no_music_wording():
    """同一个「没有音乐在放」，两处对用户说的话不同 —— 因此错误文案由调用方传入。"""
    handler = _PlayerHandler(script=[(None, None)])

    entry = ensure_player_page(
        handler,
        on_page_keys=ACCOMPANIMENT_ON_PAGE_KEYS,
        no_music_error=NO_PLAYING_MUSIC_ACCOMPANIMENT_ERROR,
    )

    assert entry.ok is False
    assert entry.error == "No music playing, cannot toggle accompaniment mode"
    assert handler.gesture_handler.clicks == []


def test_ensure_player_page_keeps_the_play_mode_default_wording():
    """不传就按播放模式那句文案 —— #423 的契约一个字没动。"""
    handler = _PlayerHandler(script=[(None, None)])

    entry = ensure_player_page(handler)

    assert entry.error == "现在没有播放音乐，无法切换模式"
