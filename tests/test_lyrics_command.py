"""`:lyrics` 的命令层契约（#430 接缝之后）。

歌词怎么拿到、歌词 tab 怎么选、QQ Music 怎么切前台，都是 `MusicUIDriverPort`
背后的事；命令层只剩折行、分组与公屏派发。因此这里断言的全是「命令层不再
自己动 UI」，取歌词的正面链路在 `tests/test_lyrics_seam.py` 里用内存驱动替身覆盖。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from ushareiplay.commands.lyrics import LyricsCommand


def _make_command():
    command = LyricsCommand.__new__(LyricsCommand)
    command.handler = MagicMock()  # soul handler
    command.music_handler = MagicMock()
    command.controller = SimpleNamespace(config={"lyrics": {"line_max_width": 18}})
    command._music_manager = MagicMock()
    command._music_manager.query_lyrics.return_value = {"lyrics": "第一行\n第二行"}
    command.music_handler.key_actions.switch_to_app.return_value = True
    command.music_handler.query_music.return_value = True
    return command


def test_query_lyrics_asks_music_manager_for_the_lyrics():
    """取歌词是接缝的职责：命令只递查询词，拿到文本后自己排版。"""
    command = _make_command()

    result = command.query_lyrics("some song")

    command._music_manager.query_lyrics.assert_called_once_with("some song")
    assert result == {"groups": ["第一行\n第二行"]}


def test_query_lyrics_leaves_every_ui_action_to_the_driver():
    """切前台、查歌、切 tab、读 DOM 全部下沉到驱动：命令层一个都不做。"""
    command = _make_command()

    command.query_lyrics("some song")

    command.music_handler.key_actions.switch_to_app.assert_not_called()
    command.music_handler.query_music.assert_not_called()
    command.music_handler.element_finder.wait_for_any_element.assert_not_called()
    command.music_handler.select_tab.assert_not_called()
    command.music_manager.select_tab.assert_not_called()


def test_query_lyrics_returns_the_seam_error_without_chunking():
    """接缝说「没找到歌词」时原样透出，一个字符都不该被发到公屏。"""
    command = _make_command()
    command._music_manager.query_lyrics.return_value = {
        "error": 'No lyrics found for "some song"'
    }

    assert command.query_lyrics("some song") == {
        "error": 'No lyrics found for "some song"'
    }
