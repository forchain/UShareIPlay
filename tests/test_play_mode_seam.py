"""Ticket #423: 播放模式切换收进 MusicManager 播放页接缝的离线测试。

测试面只有两个：`MusicManager.set_play_mode()` 与 `ModeCommand.do_process()`。
Appium 侧全部由 `tests/fakes/in_memory_music_driver.py` 的脚本化替身顶替，
因此 pytest 无需 Android 设备、Appium 服务或真实 `dumpsys` 即可跑完。

共享的播放页进入仪式（`ensure_player_page`）另外单独断言一次：它是 #421 生产
适配器、#427 伴奏、#430 歌词三处都要复用的那段 UI 前置动作，元素 key 必须全部来自
config.yaml，而不是写死在 Python 里。
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ushareiplay.commands.mode import ModeCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.driver import MusicUIDriverPort
from ushareiplay.managers.playback.models import NO_PLAYING_MUSIC_ERROR
from ushareiplay.managers.playback.player_page import (
    PLAYER_PAGE_PROBE_KEYS,
    ensure_player_page,
)
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver


class _PlayModeCache:
    """QQMusicHandler 播放模式缓存的替身：只保留 key 读写与记录。"""

    def __init__(self, play_mode_key="unknown"):
        self.play_mode_key = play_mode_key
        self.notes = []

    def note_play_mode(self, new_key, reason):
        self.notes.append((new_key, reason))
        self.play_mode_key = new_key
        return True


def _build_manager(*, driver=None, play_mode_key="unknown"):
    """真实 MusicManager + 内存驱动替身；缓存替身承担「房间当前在哪个模式」。"""
    driver = driver or InMemoryMusicUIDriver()
    cache = _PlayModeCache(play_mode_key)
    manager = MusicManager.initialize(ui_driver=driver)
    manager.music_handler = cache
    return SimpleNamespace(manager=manager, cache=cache, driver=driver)


# ---------------------------------------------------------------------------
# Slice 1: 端口契约
# ---------------------------------------------------------------------------


def test_play_mode_switching_is_part_of_the_ui_driver_port_contract():
    """端口已经变宽：只实现 start_playback 的适配器装不上。

    这条断言同时是给 #421 生产适配器的提示 —— `set_play_mode` 是抽象方法，
    漏实现会在这里显式炸掉，而不是等到用户敲 `:mode` 才失败。
    """

    class _PlayOnlyDriver(MusicUIDriverPort):
        def start_playback(self, request):
            raise AssertionError("unused")

    with pytest.raises(TypeError):
        _PlayOnlyDriver()


def test_in_memory_driver_satisfies_the_widened_port():
    assert isinstance(InMemoryMusicUIDriver(), MusicUIDriverPort)


# ---------------------------------------------------------------------------
# Slice 2: MusicManager.set_play_mode
# ---------------------------------------------------------------------------


async def test_set_play_mode_keeps_the_current_mode_without_touching_the_ui(initialized_test_singletons):
    """已经在目标模式时立即返回，一个 UI 动作都不该发生。"""
    engine = _build_manager(play_mode_key="list")

    result = await engine.manager.set_play_mode(0)

    assert result == {
        "success": True,
        "mode": "顺序播放",
        "message": "已经是顺序播放模式",
    }
    assert engine.driver.play_mode_requests == []
    assert engine.driver.play_mode_clicks == 0


async def test_set_play_mode_switches_through_the_driver_and_records_the_observed_mode(initialized_test_singletons):
    """模式切换由驱动完成，房间缓存跟随 UI 观察到的结果。"""
    engine = _build_manager(play_mode_key="list")

    result = await engine.manager.set_play_mode(-1)

    assert result == {
        "success": True,
        "mode": "随机播放",
        "message": "成功切换到随机播放模式",
    }
    assert engine.driver.play_mode_requests == ["random"]
    assert engine.driver.play_mode == "random"
    assert engine.cache.play_mode_key == "random"
    assert engine.cache.notes == [("random", "mode_ui_detect")]


async def test_set_play_mode_reports_a_mode_the_player_page_already_shows(initialized_test_singletons):
    """缓存说是 list、播放页其实已是 single：以 UI 为准，并如实说「已经是」。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(play_mode="single"),
        play_mode_key="list",
    )

    result = await engine.manager.set_play_mode(1)

    assert result == {
        "success": True,
        "mode": "单曲循环",
        "message": "已经是单曲循环模式",
    }
    assert engine.driver.play_mode_clicks == 0
    assert engine.cache.play_mode_key == "single"


async def test_set_play_mode_returns_a_localized_error_when_nothing_is_playing(initialized_test_singletons):
    """没有音乐在放时给出本地化错误，而不是让 UI 异常冒到命令层。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(no_music=True),
        play_mode_key="unknown",
    )

    result = await engine.manager.set_play_mode(1)

    assert result == {"error": NO_PLAYING_MUSIC_ERROR}
    assert NO_PLAYING_MUSIC_ERROR == "现在没有播放音乐，无法切换模式"
    # 失败也要如实记下 UI 观察到的模式（此时是未知的「没有在放」）。
    assert engine.cache.notes == []


async def test_set_play_mode_propagates_driver_failures_without_crashing(initialized_test_singletons):
    """驱动报出的失败原因原样回到命令层。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(play_mode_failures={"random": "切换失败"}),
        play_mode_key="list",
    )

    result = await engine.manager.set_play_mode(-1)

    assert result == {"error": "切换失败"}
    assert engine.cache.play_mode_key == "list"


async def test_set_play_mode_accepts_both_index_and_key_forms(initialized_test_singletons):
    """0/1/-1 与 list/single/random 是同一件事的两种写法。"""
    for value in (1, "1", "single"):
        MusicManager.reset_instance()
        engine = _build_manager(play_mode_key="list")

        result = await engine.manager.set_play_mode(value)

        assert result["mode"] == "单曲循环"
        assert engine.driver.play_mode_requests == ["single"]


async def test_set_play_mode_rejects_unknown_targets_without_touching_the_ui(initialized_test_singletons):
    """非法目标当场被拒：不进播放页，也不点任何东西。"""
    for value in (2, "replay", None, "顺序播放", True):
        MusicManager.reset_instance()
        engine = _build_manager(play_mode_key="list")

        result = await engine.manager.set_play_mode(value)

        assert result == {"error": "Invalid mode parameter, must be 0, 1 or -1"}
        assert engine.driver.play_mode_requests == []
        assert engine.cache.notes == []


async def test_set_play_mode_without_a_driver_raises_an_assembly_error(
    initialized_test_singletons,
):
    """尚未装配 UI 驱动是装配错误，不能伪装成「切换失败」回复给用户。

    #421 把生产适配器接到组合根之后，这条路径才第一次被真正走到。
    """
    manager = MusicManager.initialize()

    with pytest.raises(RuntimeError, match="MusicUIDriverPort"):
        await manager.set_play_mode(1)


async def test_set_play_mode_only_logs_when_a_switch_actually_happened(
    initialized_test_singletons,
):
    """铁律：空转不刷屏。缓存说是 list、播放页其实已经是 single 时，一条日志都不该有。

    与伴奏那条（`test_accompaniment_seam`）同一把尺子：缓存与播放页不一致是常事，
    此时零点击 —— 记一条「Play mode switched」会把空转说成切换。
    """
    logs = []

    already_on = _build_manager(
        driver=InMemoryMusicUIDriver(play_mode="single"),
        play_mode_key="list",
    )
    already_on.manager.logger = SimpleNamespace(
        info=logs.append, warning=logs.append, error=logs.append
    )
    await already_on.manager.set_play_mode(1)
    assert logs == []

    MusicManager.reset_instance()
    toggled = _build_manager(play_mode_key="list")
    toggled.manager.logger = SimpleNamespace(
        info=logs.append, warning=logs.append, error=logs.append
    )
    await toggled.manager.set_play_mode(-1)
    assert len(logs) == 1
    assert "target=random" in logs[0]


# ---------------------------------------------------------------------------
# Slice 3: ModeCommand 只做参数校验与委派
# ---------------------------------------------------------------------------


def _make_command():
    command = ModeCommand.__new__(ModeCommand)
    command._music_manager = MagicMock()
    command._music_manager.set_play_mode = AsyncMock(
        return_value={"success": True, "mode": "单曲循环", "message": "成功切换到单曲循环模式"}
    )
    return command


async def test_mode_command_requires_a_parameter():
    command = _make_command()

    result = await command.do_process(None, [])

    assert result == {"error": "Missing mode parameter"}
    command._music_manager.set_play_mode.assert_not_awaited()


async def test_mode_command_rejects_parameters_outside_zero_one_and_minus_one():
    command = _make_command()

    result = await command.do_process(None, ["2"])

    assert result == {"error": "Invalid mode parameter, must be 0, 1 or -1"}
    command._music_manager.set_play_mode.assert_not_awaited()


async def test_mode_command_delegates_the_mode_work_to_music_manager():
    """命令层不再有任何 Appium 动作：解析参数后原样返回管理器的回复。"""
    command = _make_command()

    result = await command.do_process(None, ["1"])

    command._music_manager.set_play_mode.assert_awaited_once_with(1)
    assert result == {
        "success": True,
        "mode": "单曲循环",
        "message": "成功切换到单曲循环模式",
    }
    assert not hasattr(command, "_change_play_mode_direct")


async def test_mode_command_returns_the_no_music_error_from_music_manager():
    command = _make_command()
    command._music_manager.set_play_mode.return_value = {"error": NO_PLAYING_MUSIC_ERROR}

    result = await command.do_process(None, ["-1"])

    command._music_manager.set_play_mode.assert_awaited_once_with(-1)
    assert result == {"error": "现在没有播放音乐，无法切换模式"}


# ---------------------------------------------------------------------------
# Slice 4: 共享的播放页进入仪式
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


def test_player_page_entry_keys_all_come_from_config_yaml():
    """元素选择器的唯一权威是 config.yaml：Python 里只出现 key，不出现 XPath。"""
    config = __import__("yaml").safe_load(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8")
    )
    elements = config["qq_music"]["elements"]

    assert set(PLAYER_PAGE_PROBE_KEYS) == {
        "playing_bar",
        "play_mode_list",
        "play_mode_single",
        "play_mode_random",
    }
    assert set(PLAYER_PAGE_PROBE_KEYS) <= set(elements)
    assert all(not key.startswith("//") for key in PLAYER_PAGE_PROBE_KEYS)


def test_ensure_player_page_enters_the_player_page_from_the_playing_bar():
    """底部有播放条但不在播放页：先点进去，再认当前模式。"""
    bar = object()
    mode_element = object()
    handler = _PlayerHandler(
        script=[("playing_bar", bar), ("play_mode_single", mode_element)]
    )

    entry = ensure_player_page(handler)

    assert entry.ok is True
    assert entry.mode_key == "single"
    assert entry.element is mode_element
    assert handler.gesture_handler.clicks == [bar]
    assert handler.key_actions.backs == 1
    assert handler.element_finder.calls == [
        PLAYER_PAGE_PROBE_KEYS,
        ("play_mode_list", "play_mode_single", "play_mode_random"),
    ]


def test_ensure_player_page_stays_put_when_already_on_the_player_page():
    """已经在播放页：一个元素都不点，仪式就此结束。"""
    mode_element = object()
    handler = _PlayerHandler(script=[("play_mode_list", mode_element)])

    entry = ensure_player_page(handler)

    assert entry.ok is True
    assert entry.mode_key == "list"
    assert entry.element is mode_element
    assert handler.gesture_handler.clicks == []
    assert handler.element_finder.calls == [PLAYER_PAGE_PROBE_KEYS]


def test_ensure_player_page_reports_when_nothing_is_playing():
    """既没有播放条也没有模式按钮 —— 说明没有音乐在放。"""
    handler = _PlayerHandler(script=[(None, None)])

    entry = ensure_player_page(handler)

    assert entry.ok is False
    assert entry.error == "现在没有播放音乐，无法切换模式"
    assert entry.element is None
    assert handler.gesture_handler.clicks == []


def test_ensure_player_page_reports_failure_to_foreground_the_music_app():
    """切不过去就不做后续探测，别在别的 App 上找元素。"""
    handler = _PlayerHandler(switched=False, script=[("play_mode_list", object())])

    entry = ensure_player_page(handler)

    assert entry.ok is False
    assert entry.error == "无法切换到音乐App，稍后重试"
    assert handler.element_finder.calls == []
    assert handler.gesture_handler.clicks == []


def test_ensure_player_page_reports_a_failed_tap_on_the_playing_bar():
    bar = object()
    handler = _PlayerHandler(
        script=[("playing_bar", bar)], clickable=False
    )

    entry = ensure_player_page(handler)

    assert entry.ok is False
    assert entry.error == "FAIL: 点击 playing_bar 进入播放页失败"
    assert handler.gesture_handler.clicks == [bar]


def test_ensure_player_page_reports_a_player_page_without_mode_controls():
    """点进播放页却看不到模式按钮：如实报错，不猜。"""
    handler = _PlayerHandler(
        script=[("playing_bar", object()), (None, None)]
    )

    entry = ensure_player_page(handler)

    assert entry.ok is False
    assert entry.error == "FAIL: 点击 playing_bar 后仍未找到播放模式控制元素"


def test_ensure_player_page_does_not_log_while_merely_sitting_on_the_player_page():
    """轮询式调用不得刷屏：只有真的发生了动作才记日志。"""
    handler = _PlayerHandler(script=[("play_mode_list", object())])
    logs = []
    handler.logger.info = logs.append
    handler.logger.warning = logs.append

    ensure_player_page(handler)

    assert logs == []
