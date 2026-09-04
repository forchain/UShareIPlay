import pytest

from ushareiplay.helpers.playlist_parser import PlaylistParser


@pytest.fixture
def parser():
    return PlaylistParser()


def test_parse_playlist_name_fullwidth_pipe(parser):
    subject, topic = parser.parse_playlist_name("方力申｜小方45首經典好歌")
    assert subject == "方力申"
    assert topic == "小方45首經典好歌"


def test_parse_playlist_name_cjk_radical_pipe(parser):
    subject, topic = parser.parse_playlist_name("方力申丨小方45首經典好歌")
    assert subject == "方力申"
    assert topic == "小方45首經典好歌"


def test_parse_playlist_name_ascii_pipe(parser):
    subject, topic = parser.parse_playlist_name("方力申|小方45首經典好歌")
    assert subject == "方力申"
    assert topic == "小方45首經典好歌"


def test_parse_playlist_name_strips_chinese_quotes(parser):
    subject, topic = parser.parse_playlist_name("“方力申”｜‘小方45首經典好歌’")
    assert subject == "方力申"
    assert topic == "小方45首經典好歌"


def test_parse_playlist_name_dashes(parser):
    subject1, topic1 = parser.parse_playlist_name("周杰伦—最伟大的作品")
    assert subject1 == "周杰伦"
    assert topic1 == "最伟大的作品"

    subject2, topic2 = parser.parse_playlist_name("周杰伦－最伟大的作品")
    assert subject2 == "周杰伦"
    assert topic2 == "最伟大的作品"


def test_parse_playlist_name_brackets(parser):
    subject, topic = parser.parse_playlist_name("【华语流行】精选歌单推荐")
    assert subject == "华语流行"
    assert topic == "精选歌单推荐"


def test_parse_playlist_name_no_separator(parser):
    subject, topic = parser.parse_playlist_name("周杰伦经典合集")
    assert subject == "周杰伦经典合集"
    assert topic == ""


def test_parse_playlist_name_empty_or_none(parser):
    assert parser.parse_playlist_name("") == ("", "")
    assert parser.parse_playlist_name(None) == ("", "")
