from unittest.mock import MagicMock

from ushareiplay.commands.lyrics import LyricsCommand


def _make_command():
    command = LyricsCommand.__new__(LyricsCommand)
    command.handler = MagicMock()  # soul handler
    command.music_handler = MagicMock()
    command._music_manager = MagicMock()
    command.music_handler.key_actions.switch_to_app.return_value = True
    command.music_handler.query_music.return_value = True
    return command


def test_query_lyrics_requests_lyrics_tab_through_music_manager():
    """歌词 tab 的选择是 MusicManager 的职责：命令不再自己滚容器/找元素。"""
    command = _make_command()
    command._music_manager.select_tab.return_value = False

    result = command.query_lyrics("some song")

    command._music_manager.select_tab.assert_called_once_with("lyrics")
    command.music_handler.gesture_handler.scroll_container_until_element.assert_not_called()
    assert result == {"error": "Failed to select lyrics tab"}


def test_query_lyrics_foregrounds_music_app_before_selecting_tab():
    command = _make_command()
    command._music_manager.select_tab.return_value = False

    command.query_lyrics("some song")

    command.music_handler.key_actions.switch_to_app.assert_called()
