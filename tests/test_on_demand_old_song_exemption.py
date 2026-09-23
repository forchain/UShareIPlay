"""Ticket #318: on-demand requests bypass the old-song filter.

An explicit `:play` / `:next` request is a strong single-song intent: the song
the user asked for must play even when it was released before the configured
cutoff. Radio and auto-playlist playback keep following the filter, and the
exemption expires once the requested song has played.
"""

from types import SimpleNamespace

from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


OLD_SONG = {"song": "老歌", "singer": "歌手A", "album": "专辑A"}
OTHER_OLD_SONG = {"song": "另一首老歌", "singer": "歌手B", "album": "专辑B"}


class _FakeMusicHandler:
    """Mirrors the QQMusicHandler state the quality policy reads."""

    def __init__(self, release_date="1999-01-01"):
        self.logger = _Logger()
        self.list_mode = "unknown"
        self.no_skip = 0
        self.config = {"old_song_filter": {"enabled": True, "cutoff_date": "2000-01-01"}}
        self.release_date = release_date


def _make_music_manager(handler=None):
    from ushareiplay.managers.music_manager import MusicManager

    manager = MusicManager.__new__(MusicManager)
    manager._handler = None
    manager.logger = _Logger()
    handler = handler or _FakeMusicHandler()
    manager.music_handler = handler
    manager._song_release_lookup = SimpleNamespace(
        get_release_date=lambda _query: handler.release_date
    )
    manager._on_demand_song = None
    manager._on_demand_matched = False
    manager.skipped = []
    manager.skip_song = lambda: manager.skipped.append(True) or {}
    return manager


class _FakeDispatch:
    def __init__(self):
        self.screen_messages = []

    def send_screen_message(self, message, silent=False):
        self.screen_messages.append(message)


def _make_broadcaster(manager):
    PlaybackBroadcaster.reset_instance()
    broadcaster = PlaybackBroadcaster.initialize()
    broadcaster._logger = _Logger()
    broadcaster._music_manager = manager
    broadcaster._soul_handler = SimpleNamespace(config={"broadcast_playing_info": True})
    broadcaster._message_dispatch = _FakeDispatch()
    return broadcaster


# --------------------------------------------------------------------------
# Quality policy: on-demand exemption
# --------------------------------------------------------------------------


def test_on_demand_old_song_is_not_skipped():
    manager = _make_music_manager()
    manager.mark_on_demand(dict(OLD_SONG))
    song_info = dict(OLD_SONG)

    should_skip = manager.should_skip_low_quality_song(song_info)

    assert should_skip is False
    # The filter still ran and resolved the release date; it just accepted the song.
    assert song_info["release_date"] == "1999-01-01"


def test_on_demand_old_song_is_not_skipped_by_handle_quality_check():
    manager = _make_music_manager()
    manager.mark_on_demand(dict(OLD_SONG))

    skipped = manager.handle_song_quality_check(dict(OLD_SONG))

    assert skipped is False
    assert manager.skipped == []


def test_auto_playlist_old_song_is_still_skipped():
    manager = _make_music_manager()

    skipped = manager.handle_song_quality_check(dict(OLD_SONG))

    assert skipped is True
    assert manager.skipped == [True]


def test_other_old_song_is_still_skipped_while_a_request_is_pending():
    """Only the requested song is exempt; the rest of the room playlist is not."""
    manager = _make_music_manager()
    manager.mark_on_demand(dict(OLD_SONG))

    skipped = manager.handle_song_quality_check(dict(OTHER_OLD_SONG))

    assert skipped is True
    assert manager.skipped == [True]


def test_exemption_expires_after_the_requested_song_has_played():
    """Radio replaying the same old song later is filtered again."""
    manager = _make_music_manager()
    manager.mark_on_demand(dict(OLD_SONG))

    # The requested song plays (broadcast/quality check path).
    assert manager.should_skip_low_quality_song(dict(OLD_SONG)) is False
    # The room moves on to another song.
    assert manager.should_skip_low_quality_song(dict(OTHER_OLD_SONG)) is True
    # Same title coming back from an auto playlist is filtered again.
    assert manager.should_skip_low_quality_song(dict(OLD_SONG)) is True
    assert manager.skipped == []


def test_exemption_survives_stale_playback_reports_before_the_song_plays():
    """Metadata lag must not burn the exemption before the requested song starts."""
    manager = _make_music_manager()
    manager.mark_on_demand(dict(OLD_SONG))

    assert manager.should_skip_low_quality_song(
        {"song": "Unknown", "singer": "Unknown", "album": "Unknown"}) is True
    assert manager.should_skip_low_quality_song(dict(OLD_SONG)) is False


def test_on_demand_mark_matches_media_session_title_with_version_suffix():
    manager = _make_music_manager()
    manager.mark_on_demand({"song": "海阔天空", "singer": "Beyond"})

    should_skip = manager.should_skip_low_quality_song(
        {"song": "海阔天空 (Live)", "singer": "Beyond", "album": "乐与怒"}
    )

    assert should_skip is False


def test_cover_with_the_same_title_is_not_exempted():
    """A different artist's track with the same title is not the requested song."""
    manager = _make_music_manager()
    manager.mark_on_demand(dict(OLD_SONG))

    should_skip = manager.should_skip_low_quality_song(
        {"song": "老歌", "singer": "翻唱歌手", "album": "翻唱专辑"}
    )

    assert should_skip is True


def test_on_demand_does_not_exempt_other_quality_rules():
    """The exemption covers the old-song filter only, not DJ/Remix matching."""
    manager = _make_music_manager()
    manager.mark_on_demand({"song": "绝版 Remix", "singer": "歌手A"})

    should_skip = manager.should_skip_low_quality_song(
        {"song": "绝版 Remix", "singer": "歌手A", "album": "专辑A"}
    )

    assert should_skip is True


def test_late_quality_check_after_play_still_exempts_the_requested_song():
    """The broadcaster re-checks the same song from MediaSession metadata."""
    manager = _make_music_manager()
    manager.mark_on_demand(dict(OLD_SONG))

    assert manager.is_on_demand_playback(dict(OLD_SONG)) is True
    assert manager.is_on_demand_playback(dict(OLD_SONG)) is True


# --------------------------------------------------------------------------
# PlaybackBroadcaster: still broadcasts an on-demand old song
# --------------------------------------------------------------------------


def test_broadcaster_sends_message_for_on_demand_old_song():
    manager = _make_music_manager()
    manager.mark_on_demand(dict(OLD_SONG))
    broadcaster = _make_broadcaster(manager)
    broadcaster._playback_info_cache = dict(OLD_SONG)

    broadcaster.send_playing_message()

    assert manager.skipped == []
    # Still broadcast, with the release date the filter resolved on the way through.
    assert broadcaster.message_dispatch.screen_messages == ["老歌 - 歌手A • 专辑A 1999-01-01"]


def test_broadcaster_skips_old_song_from_auto_playlist():
    manager = _make_music_manager()
    broadcaster = _make_broadcaster(manager)
    broadcaster._playback_info_cache = dict(OLD_SONG)

    broadcaster.send_playing_message()

    assert manager.skipped == [True]
    assert broadcaster.message_dispatch.screen_messages == []


# --------------------------------------------------------------------------
# Request path: :play / :next mark the requested song as on demand
# --------------------------------------------------------------------------


class _RecordingMusicManager:
    def __init__(self):
        self.marked = []

    def mark_on_demand(self, song_info):
        self.marked.append(song_info)


class _FakeElementFinder:
    """Minimal element finder serving the search-result screen."""

    def __init__(self, elements):
        self.elements = elements

    def wait_for_any_element(self, _keys):
        return "first_song", self.elements["first_song"]

    def try_find_element(self, key, log=True):
        return self.elements.get(key)

    def wait_for_element_clickable(self, key, timeout=None):
        return self.elements.get(key)

    def wait_for_element(self, key):
        return self.elements.get(key)


def _make_qq_handler(playing_info):
    from ushareiplay.handlers.qq_music_handler import QQMusicHandler

    handler = QQMusicHandler.__new__(QQMusicHandler)
    handler.logger = _Logger()
    handler.list_mode = "unknown"
    handler.no_skip = 0
    handler.query_music = lambda _query: "search_entry"
    handler.select_song_tab = lambda: True
    handler.get_playing_info = lambda: playing_info
    handler.element_finder = _FakeElementFinder(
        {"first_song": SimpleNamespace(text="老歌"), "next_button": SimpleNamespace(click=lambda: None)}
    )
    return handler


def test_explicit_play_marks_the_requested_song_on_demand(monkeypatch):
    """`:play <song>` goes through the shared request seam and registers intent."""
    playing_info = dict(OLD_SONG)
    handler = _make_qq_handler(playing_info)
    manager = _RecordingMusicManager()
    monkeypatch.setattr(
        "ushareiplay.managers.music_manager.MusicManager.instance",
        staticmethod(lambda: manager),
    )

    result = handler._prepare_music_playback("老歌 歌手A")

    assert result == playing_info
    assert manager.marked == [playing_info]


def test_explicit_next_marks_the_queued_song_on_demand(monkeypatch):
    """`:next <song>` shares the same seam, so the queued song is exempt too."""
    playing_info = dict(OLD_SONG)
    handler = _make_qq_handler(playing_info)
    manager = _RecordingMusicManager()
    monkeypatch.setattr(
        "ushareiplay.managers.music_manager.MusicManager.instance",
        staticmethod(lambda: manager),
    )

    handler.play_next("老歌 歌手A")

    assert manager.marked == [playing_info]


def test_failed_search_does_not_register_on_demand_intent(monkeypatch):
    handler = _make_qq_handler(dict(OLD_SONG))
    handler.query_music = lambda _query: None
    manager = _RecordingMusicManager()
    monkeypatch.setattr(
        "ushareiplay.managers.music_manager.MusicManager.instance",
        staticmethod(lambda: manager),
    )

    result = handler._prepare_music_playback("不存在")

    assert "error" in result
    assert manager.marked == []
