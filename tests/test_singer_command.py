from unittest.mock import MagicMock
from ushareiplay.commands.singer import SingerCommand


def test_select_singer_tab_scrolls_and_clicks():
    command = SingerCommand.__new__(SingerCommand)
    command.handler = MagicMock()

    singer_tab = MagicMock()
    command.handler.element_finder.try_find_element.return_value = None
    command.handler.gesture_handler.scroll_container_until_element.return_value = (
        "singer_tab", singer_tab, []
    )

    assert command.select_singer_tab() is True
    singer_tab.click.assert_called_once_with()
    command.handler.gesture_handler.scroll_container_until_element.assert_called_once_with(
        "singer_tab", "music_tabs", "left", max_swipes=10
    )


def test_play_singer_falls_back_to_singer_tab_when_first_song_not_found():
    command = SingerCommand.__new__(SingerCommand)
    command.handler = MagicMock()
    command._info_manager = MagicMock()
    command._title_manager = MagicMock()
    command._topic_manager = MagicMock()

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

    command.select_singer_tab = MagicMock(return_value=True)

    result = command.play_singer("Lofi Girl")

    command.select_singer_tab.assert_called_once()
    singer_result.click.assert_called_once()
    play_all_button.click.assert_called_once()
    assert result == {"playlist": "Lofi Girl"}
