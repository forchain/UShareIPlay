from pathlib import Path

import yaml

from ushareiplay.helpers.playlist_info import get_playlist_text_and_first_song


def test_get_playlist_text_and_first_song_returns_trimmed_playlist_and_first_song():
    playlist_text, first_song, error = get_playlist_text_and_first_song(
        {"playlist": " 第一首 - 歌手A \n第二首 - 歌手B "}
    )

    assert error is None
    assert playlist_text == "第一首 - 歌手A \n第二首 - 歌手B"
    assert first_song == "第一首 - 歌手A"


def test_get_playlist_text_and_first_song_returns_error_from_handler():
    playlist_text, first_song, error = get_playlist_text_and_first_song(
        {"error": "No songs found in playlist"}
    )

    assert playlist_text is None
    assert first_song is None
    assert error == "No songs found in playlist"


def test_get_playlist_text_and_first_song_rejects_empty_playlist():
    playlist_text, first_song, error = get_playlist_text_and_first_song({"playlist": " \n "})

    assert playlist_text is None
    assert first_song is None
    assert error == "Playlist content is empty"


def test_list_play_commands_use_playlist_response_template():
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    commands = {item["prefix"]: item for item in config["commands"]}

    assert commands["playlist"]["response_template"] == "{playlist}"
    assert commands["radio"]["response_template"] == "{playlist}"
    assert commands["singer"]["response_template"] == "{playlist}"
    assert commands["album"]["response_template"] == "{playlist}"
    assert commands["fav"]["response_template"] == "{playlist}"
