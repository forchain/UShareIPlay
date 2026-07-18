from types import SimpleNamespace
from unittest.mock import MagicMock

from ushareiplay.commands.lyrics import LyricsCommand


def test_select_lyrics_tab_relocates_target_after_scroll():
    command = LyricsCommand.__new__(LyricsCommand)
    command.handler = MagicMock()
    command.music_handler = MagicMock()
    command.music_handler.key_actions.switch_to_app.return_value = True

    container_marker = MagicMock()
    lyrics_tab = MagicMock()
    command.music_handler.element_finder.try_find_element.side_effect = [
        None,
        lyrics_tab,
    ]
    command.music_handler.gesture_handler.scroll_container_until_element.return_value = (
        "lyrics_tab", container_marker, []
    )

    assert command.select_lyrics_tab() is True
    lyrics_tab.click.assert_called_once_with()
    container_marker.click.assert_not_called()

