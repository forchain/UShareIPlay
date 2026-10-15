"""Ticket #430: 歌词查询收进 MusicManager 播放页接缝的离线测试。

测试面只有两个：`MusicManager.query_lyrics()` 与 `LyricsCommand.do_process()`。
Appium 侧全部由 `tests/fakes/in_memory_music_driver.py` 的脚本化替身顶替，
因此 pytest 无需 Android 设备、Appium 服务或真实 `dumpsys` 即可跑完。

词法的两半（`wrap_line_at_spaces` 折行、`process_lyrics` 分组）仍留在命令里，
因此分组断言在这一层做；接缝层只断言「歌词是怎么被拿到的」。
"""

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.commands.lyrics import LyricsCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.driver import MusicUIDriverPort
from tests.fakes.in_memory_music_driver import InMemoryMusicUIDriver


def _build_manager(*, driver=None, playback_info=None):
    """真实 MusicManager + 内存驱动替身。

    `playback_info` 是 `get_playback_info()` 的替身：MediaSession 的 dumpsys 解析
    与歌词接缝无关，歌词只需要「当前这首歌叫什么」这一个事实。
    """
    driver = driver or InMemoryMusicUIDriver()
    manager = MusicManager.initialize(ui_driver=driver)
    manager.music_handler = SimpleNamespace(
        logger=MagicMock(),
        play_mode_key="unknown",
        note_play_mode=lambda key, reason: None,
    )
    if playback_info is not None:
        manager.get_playback_info = lambda: playback_info
    return SimpleNamespace(manager=manager, driver=driver)


# ---------------------------------------------------------------------------
# Slice 1: 端口契约
# ---------------------------------------------------------------------------


def test_lyrics_retrieval_is_part_of_the_ui_driver_port_contract():
    """端口已经变宽：只实现播放与模式切换的适配器装不上。

    这条断言同时是给 #421 生产适配器的提示 —— `query_lyrics` 是抽象方法，
    漏实现会在这里显式炸掉，而不是等到用户敲 `:lyrics` 才失败。
    """

    class _PlaybackOnlyDriver(MusicUIDriverPort):
        def start_playback(self, request):
            raise AssertionError("unused")

        def set_play_mode(self, target_mode):
            raise AssertionError("unused")

    with pytest.raises(TypeError):
        _PlaybackOnlyDriver()


def test_in_memory_driver_satisfies_the_lyrics_port():
    assert isinstance(InMemoryMusicUIDriver(), MusicUIDriverPort)


# ---------------------------------------------------------------------------
# Slice 2: MusicManager.query_lyrics
# ---------------------------------------------------------------------------


def test_query_lyrics_returns_the_scripted_text_for_an_explicit_query(
    initialized_test_singletons,
):
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(lyrics={"稻香 周杰伦": "对这个世界如果你有太多的抱怨\n快回到你最初纯真的怀抱"})
    )

    result = engine.manager.query_lyrics("稻香 周杰伦")

    assert result == {"lyrics": "对这个世界如果你有太多的抱怨\n快回到你最初纯真的怀抱"}
    assert engine.driver.lyrics_requests == ["稻香 周杰伦"]


def test_query_lyrics_falls_back_to_the_current_song_when_query_is_empty(
    initialized_test_singletons,
):
    """不带查询词就问当前正在放的这首 —— 兜底只做一次，且发生在 UI 动作之前。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(lyrics={"稻香 周杰伦 七里香": "对这个世界如果你有太多的抱怨"}),
        playback_info={"song": "稻香", "singer": "周杰伦", "album": "七里香", "state": "Playing"},
    )

    result = engine.manager.query_lyrics()

    assert result == {"lyrics": "对这个世界如果你有太多的抱怨"}
    assert engine.driver.lyrics_requests == ["稻香 周杰伦 七里香"]


def test_query_lyrics_treats_a_blank_query_as_no_query(initialized_test_singletons):
    """只有空白字符时同样按「没给查询词」处理，不去搜一串空格。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(),
        playback_info={"song": "青花瓷", "singer": "周杰伦", "album": "我很忙", "state": "Playing"},
    )

    engine.manager.query_lyrics("   ")

    assert engine.driver.lyrics_requests == ["青花瓷 周杰伦 我很忙"]


def test_query_lyrics_reports_missing_playback_info_without_touching_the_ui(
    initialized_test_singletons,
):
    """兜底拿不到当前曲目就如实报错：一个 UI 动作都不该发生。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(),
        playback_info={"error": "Failed to get playback information"},
    )

    result = engine.manager.query_lyrics()

    assert result == {"error": "Failed to get playback info"}
    assert engine.driver.lyrics_requests == []


def test_query_lyrics_returns_a_clean_error_when_lyrics_are_not_found(
    initialized_test_singletons,
):
    """搜不到歌词是正常结局：一个干净的错误字典，不抛异常。"""
    engine = _build_manager(driver=InMemoryMusicUIDriver(not_found_lyrics=True))

    result = engine.manager.query_lyrics("一首没人唱过的歌")

    assert result == {"error": 'No lyrics found for "一首没人唱过的歌"'}
    assert engine.driver.lyrics_requests == ["一首没人唱过的歌"]


def test_query_lyrics_propagates_driver_failures_without_crashing(
    initialized_test_singletons,
):
    """驱动报出的失败原因原样回到命令层。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(lyrics_failures={"任意": "Failed to select lyrics tab"})
    )

    result = engine.manager.query_lyrics("任意")

    assert result == {"error": "Failed to select lyrics tab"}


def test_query_lyrics_records_the_lookup_in_the_shared_journal(initialized_test_singletons):
    """查询会落在共享时间线上：谁动了 UI、在什么时刻，一目了然。"""
    journal = []
    engine = _build_manager(driver=InMemoryMusicUIDriver(journal=journal))

    engine.manager.query_lyrics("夜曲 周杰伦")

    assert journal == ["lyrics:夜曲 周杰伦"]


def test_query_lyrics_without_a_driver_raises_an_assembly_error(
    initialized_test_singletons,
):
    """尚未装配 UI 驱动是装配错误，不能伪装成「没找到歌词」回复给用户。

    #421 把生产适配器接到组合根之后，这条路径才第一次被真正走到。
    """
    manager = MusicManager.initialize()

    with pytest.raises(RuntimeError, match="MusicUIDriverPort"):
        manager.query_lyrics("夜曲")


# ---------------------------------------------------------------------------
# Slice 3: LyricsCommand 只做折行、分组与派发
# ---------------------------------------------------------------------------


def _make_command(*, lyrics="第一行\n第二行\n第三行", config=None):
    command = LyricsCommand.__new__(LyricsCommand)
    command.handler = MagicMock()  # soul handler
    command.music_handler = MagicMock()  # 命令层不该再碰它
    command.controller = SimpleNamespace(config=config if config is not None else {})
    command._music_manager = MagicMock()
    command._music_manager.query_lyrics.return_value = {"lyrics": lyrics}
    command._message_dispatch = MagicMock()
    return command


def test_lyrics_command_keeps_no_ui_automation_of_its_own():
    """命令模块只剩排版与派发：查歌、切 tab、点元素、读 DOM 都在接缝后面。"""
    source = inspect.getsource(LyricsCommand)

    for forbidden in (
        "element_finder",
        "wait_for_any_element",
        ".click()",
        "query_music",
        "unescape",
        "switch_to_app",
        "select_tab",
    ):
        assert forbidden not in source, forbidden


def test_query_lyrics_delegates_the_lookup_to_music_manager():
    """歌词的取法由管理器决定：命令只把查询词递过去。"""
    command = _make_command()

    result = command.query_lyrics("some song")

    command._music_manager.query_lyrics.assert_called_once_with("some song")
    assert result == {"groups": ["第一行\n第二行\n第三行"]}


def test_query_lyrics_does_not_touch_the_music_handler():
    """接缝的另一面：一个 UI 调用都不该从命令层漏出去。"""
    command = _make_command()

    command.query_lyrics("some song")

    command.music_handler.key_actions.switch_to_app.assert_not_called()
    command.music_handler.query_music.assert_not_called()
    command.music_handler.element_finder.wait_for_any_element.assert_not_called()
    command.music_handler.select_tab.assert_not_called()


def test_query_lyrics_returns_the_manager_error_untouched():
    command = _make_command()
    command._music_manager.query_lyrics.return_value = {
        "error": 'No lyrics found for "some song"'
    }

    assert command.query_lyrics("some song") == {
        "error": 'No lyrics found for "some song"'
    }
    command._message_dispatch.send_screen_message.assert_not_called()


def test_query_lyrics_wraps_long_lines_at_the_configured_width():
    """折行宽度来自 config.yaml 的 `lyrics.line_max_width`。"""
    command = _make_command(
        lyrics="a" * 30, config={"lyrics": {"line_max_width": 12}}
    )

    result = command.query_lyrics("some song")

    assert result == {"groups": ["a" * 12 + "\n" + "a" * 12 + "\n" + "a" * 6]}


def test_query_lyrics_falls_back_to_the_default_width_without_lyrics_config():
    """配置里没有 lyrics 段时用 18，不因此崩。"""
    command = _make_command(lyrics="a" * 30, config={})

    result = command.query_lyrics("some song")

    assert result == {"groups": ["a" * 18 + "\n" + "a" * 12]}


def test_query_lyrics_chunks_the_lyrics_into_the_requested_number_of_groups():
    """`force_groups` 是词法分组的契约：用户要几段就给几段。"""
    command = _make_command(lyrics="\n".join(["0123456789"] * 6))

    result = command.query_lyrics("some song", 2)

    assert len(result["groups"]) == 2
    assert all(len(group.split("\n")) == 3 for group in result["groups"])


async def test_do_process_sends_each_group_to_the_chat_screen(initialized_test_singletons):
    """从命令到接缝的完整链路：管理器拿歌词，命令分组并逐条发公屏。"""
    engine = _build_manager(
        driver=InMemoryMusicUIDriver(lyrics={"稻香 周杰伦": "对这个世界如果你有太多的抱怨"}),
    )
    command = LyricsCommand.__new__(LyricsCommand)
    command.handler = MagicMock()
    command.controller = SimpleNamespace(config={"lyrics": {"line_max_width": 16}})
    command._music_manager = engine.manager
    command._message_dispatch = MagicMock()

    result = await command.do_process(None, ["稻香", "周杰伦"])

    assert result == {"lyrics": " 1 piece(s) of lyrics sent, 14 characters"}
    command._message_dispatch.send_screen_message.assert_called_once_with(
        "对这个世界如果你有太多的抱怨"
    )
    assert engine.driver.lyrics_requests == ["稻香 周杰伦"]


async def test_do_process_parses_a_leading_integer_as_the_group_count(
    initialized_test_singletons,
):
    engine = _build_manager(driver=InMemoryMusicUIDriver(lyrics={"稻香": "\n".join(["0123456789"] * 6)}))
    command = LyricsCommand.__new__(LyricsCommand)
    command.handler = MagicMock()
    command.controller = SimpleNamespace(config={})
    command._music_manager = engine.manager
    command._message_dispatch = MagicMock()

    result = await command.do_process(None, ["2", "稻香"])

    # 两组各 3 行、每行 10 字：分组处各少一个换行，因此是 64 而不是原文的 65。
    assert result == {"lyrics": " 2 piece(s) of lyrics sent, 64 characters"}
    assert engine.driver.lyrics_requests == ["稻香"]
    assert command._message_dispatch.send_screen_message.call_count == 2


async def test_do_process_asks_for_the_current_song_without_parameters(
    initialized_test_singletons,
):
    """`:lyrics` 无参数：查询词为空，由管理器兜底成当前曲目。"""
    engine = _build_manager(driver=InMemoryMusicUIDriver())
    command = LyricsCommand.__new__(LyricsCommand)
    command.handler = MagicMock()
    command.controller = SimpleNamespace(config={})
    command._music_manager = engine.manager
    command._message_dispatch = MagicMock()
    engine.manager.get_playback_info = lambda: {
        "song": "夜曲",
        "singer": "周杰伦",
        "album": "十一月的萧邦",
        "state": "Playing",
    }

    await command.do_process(None, [])

    assert engine.driver.lyrics_requests == ["夜曲 周杰伦 十一月的萧邦"]


async def test_do_process_surfaces_the_manager_error_to_the_room(initialized_test_singletons):
    """接缝的失败原样透给公屏，命令层不自己拼文案。"""
    engine = _build_manager(driver=InMemoryMusicUIDriver(not_found_lyrics=True))
    command = LyricsCommand.__new__(LyricsCommand)
    command.handler = MagicMock()
    command.controller = SimpleNamespace(config={})
    command._music_manager = engine.manager
    command._message_dispatch = MagicMock()

    result = await command.do_process(None, ["不存在的歌"])

    assert result == {"error": 'No lyrics found for "不存在的歌"'}
    command._message_dispatch.send_screen_message.assert_not_called()
