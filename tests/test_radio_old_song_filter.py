"""统一歌曲质量检查（老歌过滤）的离线测试。

这些用例守的是「判定只有一个实现」：`MusicManager` 里的发行日期查询、截止日期
比较与点播豁免。:radio 曾自带第二份同样逻辑的副本（#431 已删除），精选频道
「换到不老是老歌为止」那条换推荐编排连同它对这套判定的调用，现在在
`tests/test_radio_seam.py` 里按驱动接缝考。
"""

from types import SimpleNamespace


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


class _Element:
    def __init__(self, text=""):
        self.text = text
        self.clicks = 0

    def click(self):
        self.clicks += 1


class _FakeMusicHandler:
    def __init__(self):
        self.logger = _Logger()
        self.list_mode = "playlist"
        self.no_skip = 0
        self.config = {
            "old_song_filter": {
                "enabled": True,
                "cutoff_date": "2000-01-01",
            }
        }


def _make_music_manager_for_quality_check():
    from ushareiplay.managers.music_manager import MusicManager
    manager = MusicManager.__new__(MusicManager)
    manager._handler = None
    manager.logger = _Logger()
    manager._song_release_lookup = None
    manager.music_handler = _FakeMusicHandler()
    return manager


def test_quality_check_skips_old_song_for_any_playback_mode(monkeypatch):
    manager = _make_music_manager_for_quality_check()
    manager._song_release_lookup = SimpleNamespace(get_release_date=lambda _song: "1999-01-01")

    should_skip = manager.should_skip_low_quality_song(
        {"song": "老歌", "singer": "歌手A", "album": "专辑A"}
    )

    assert should_skip is True


def test_quality_check_accepts_old_song_for_whitelisted_artist(monkeypatch):
    manager = _make_music_manager_for_quality_check()
    manager.music_handler.config["old_song_filter"]["artist_whitelist"] = ["歌手A"]
    manager._song_release_lookup = SimpleNamespace(get_release_date=lambda _song: "1999-01-01")
    song_info = {"song": "老歌", "singer": "歌手A/歌手B", "album": "专辑A"}

    should_skip = manager.should_skip_low_quality_song(song_info)

    assert should_skip is False
    assert song_info["release_date"] == "1999-01-01"


def test_quality_check_reads_artist_whitelist_from_controller_config(monkeypatch):
    manager = _make_music_manager_for_quality_check()
    manager.music_handler.config = {}
    manager.music_handler.controller = SimpleNamespace(
        config={
            "old_song_filter": {
                "enabled": True,
                "cutoff_date": "2000-01-01",
                "artist_whitelist": ["王菲", "911"],
            }
        }
    )
    manager._song_release_lookup = SimpleNamespace(get_release_date=lambda _song: "1993-09-07")
    song_info = {"song": "如风", "singer": "王菲", "album": "十万个为什么？(日本版）"}

    should_skip = manager.should_skip_low_quality_song(song_info)

    assert should_skip is False
    assert song_info["release_date"] == "1993-09-07"


def test_quality_check_accepts_new_song_for_any_playback_mode(monkeypatch):
    manager = _make_music_manager_for_quality_check()
    manager._song_release_lookup = SimpleNamespace(get_release_date=lambda _song: "2018-01-01")
    song_info = {"song": "新歌", "singer": "歌手A", "album": "专辑A"}

    should_skip = manager.should_skip_low_quality_song(song_info)

    assert should_skip is False
    assert song_info["release_date"] == "2018-01-01"


def test_ensure_release_date_populates_song_info_without_skip_decision(monkeypatch):
    manager = _make_music_manager_for_quality_check()
    manager._song_release_lookup = SimpleNamespace(get_release_date=lambda _song: "1993-09-07")
    song_info = {"song": "如风", "singer": "王菲", "album": "十万个为什么？(日本版）"}

    manager.ensure_release_date(song_info)

    assert song_info["release_date"] == "1993-09-07"


class _PlayMusicHandler:
    def __init__(self):
        self.logger = _Logger()
        self.first_song = _Element("first_song")
        self.quality_checked = []
        self.playing_info = {
            "song": "似是故人来",
            "singer": "梅艳芳",
            "album": "戏剧人生",
        }

    def _prepare_music_playback(self, music_query):
        assert music_query == "似是故人来 梅艳芳"
        return self.playing_info

    def wait_for_element_clickable(self, key):
        assert key == "first_song"
        return self.first_song

    @property
    def element_finder(self):
        return self

    def ensure_favorited_in_playing_page(self, timeout=10):
        assert timeout == 10
        return True

    def handle_song_quality_check(self, song_info):
        self.quality_checked.append(song_info)
        return True


def test_play_driver_checks_song_quality_immediately_after_playback_starts(monkeypatch):
    """#421：查歌/点播/质量过滤的编排已移入 `QQMusicUIDriver`，命令不再自己点歌。

    断言仍落在「质量过滤发生在播放刚起来的同一时刻」这个行为上，只是不再经由
    `PlayCommand.play_song` —— 那条路现在是 `MusicManager.play()` 的引擎流水线。
    """
    from ushareiplay.managers.playback.models import PlaybackRequest
    from ushareiplay.managers.playback.qq_music_ui_driver import QQMusicUIDriver

    music_handler = _PlayMusicHandler()
    quality_checked = []

    class _FakeMusicManager:
        def handle_song_quality_check(self, song_info):
            quality_checked.append(song_info)
            return True

    monkeypatch.setattr(
        "ushareiplay.managers.music_manager.MusicManager.instance",
        staticmethod(lambda: _FakeMusicManager()),
    )

    outcome = QQMusicUIDriver(music_handler).start_playback(
        PlaybackRequest.song("似是故人来 梅艳芳", requester="小明")
    )

    assert outcome.ok is True
    assert music_handler.first_song.clicks == 1
    assert quality_checked == [music_handler.playing_info]


def test_play_driver_returns_error_when_first_song_not_found(monkeypatch):
    from ushareiplay.managers.playback.models import PlaybackRequest
    from ushareiplay.managers.playback.qq_music_ui_driver import QQMusicUIDriver

    music_handler = _PlayMusicHandler()
    music_handler.wait_for_element_clickable = lambda key: None

    outcome = QQMusicUIDriver(music_handler).start_playback(
        PlaybackRequest.song("似是故人来 梅艳芳", requester="小明")
    )

    assert outcome.ok is False
    assert "first song" in outcome.error
