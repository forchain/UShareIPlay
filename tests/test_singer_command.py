from unittest.mock import MagicMock
from ushareiplay.commands.singer import SingerCommand


def test_play_singer_falls_back_to_singer_tab_when_first_song_not_found():
    command = SingerCommand.__new__(SingerCommand)
    command.handler = MagicMock()
    command._info_manager = MagicMock()
    command._room_name_manager = MagicMock()
    command._topic_manager = MagicMock()
    command._music_manager = MagicMock()

    command.handler.query_music.return_value = "home_nav"
    # When home_nav is returned, wait_for_any_element for first_song returns (None, None)
    # Then wait_for_any_element for singer_result returns ("singer_result", singer_result)
    singer_result = MagicMock()
    singer_result.text = "Lofi Girl"
    play_all_button = MagicMock()

    command.handler.element_finder.try_find_element.return_value = None
    command.handler.element_finder.wait_for_any_element.side_effect = [
        ("music_tabs", MagicMock()),  # music_tabs wait
        ("singer_result", singer_result),  # singer_result wait
    ]
    command.handler.element_finder.wait_for_element_clickable.return_value = play_all_button
    command.handler.get_playlist_info.return_value = []

    result = command.play_singer("Lofi Girl")

    command._music_manager.select_tab.assert_called_once_with("singer")
    singer_result.click.assert_called_once()
    play_all_button.click.assert_called_once()
    assert result == {"playlist": "Lofi Girl"}


def test_singer_tab_selection_goes_through_music_manager_only():
    """歌手 tab 的选择是 MusicManager 的职责：命令不再自己找元素/滚容器。"""
    command = SingerCommand.__new__(SingerCommand)
    command.handler = MagicMock()
    command._info_manager = MagicMock()
    command._room_name_manager = MagicMock()
    command._topic_manager = MagicMock()
    command._music_manager = MagicMock()

    command.handler.query_music.return_value = "home_nav"
    command.handler.element_finder.try_find_element.return_value = None
    command.handler.element_finder.wait_for_any_element.side_effect = [
        ("music_tabs", MagicMock()),
    ]
    command._music_manager.select_tab.return_value = False

    result = command.play_singer("Lofi Girl")

    command._music_manager.select_tab.assert_called_once_with("singer")
    assert result == {"error": "not found singer with query Lofi Girl"}
