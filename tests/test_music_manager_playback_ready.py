"""Ticket #298: MusicManager.wait_for_playback_ready — adaptive MediaSession readiness.

Tests drive the real dumpsys parsing path (get_current_song_info) through a fake
ADB driver, with an injected fake clock so no real sleeping occurs.
"""

from types import SimpleNamespace

import pytest

from ushareiplay.managers.music_manager import MusicManager


class _Logger:
    def __init__(self):
        self.warnings = []

    def info(self, _msg):
        pass

    def warning(self, msg):
        self.warnings.append(msg)

    def error(self, _msg):
        pass


class _FakeClock:
    """Monotonic clock that advances only when the code under test sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeDriver:
    """Replays scripted `dumpsys media_session` outputs; repeats the last one."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def execute_script(self, _script, _args=None):
        self.calls += 1
        if len(self.outputs) > 1:
            return self.outputs.pop(0)
        return self.outputs[0]


def _dumpsys(song="未知歌曲", singer="未知歌手", album="未知专辑", state=6):
    return (
        f"  metadata: size=48, description={song}, {singer}, {album}\n"
        f"  state=PlaybackState {{state={state}, position=1000, buffered position=0}}\n"
    )


def _make_manager(outputs, monkeypatch):
    manager = MusicManager.__new__(MusicManager)
    manager.logger = _Logger()
    manager.music_handler = SimpleNamespace()
    manager.driver = _FakeDriver(outputs)
    manager._song_release_lookup = None

    clock = _FakeClock()
    monkeypatch.setattr(
        "ushareiplay.managers.music_manager.time.monotonic", clock.monotonic
    )
    monkeypatch.setattr("ushareiplay.managers.music_manager.time.sleep", clock.sleep)
    return manager, clock


def test_wait_for_playback_ready_returns_true_after_buffering_transitions_to_playing(
    monkeypatch,
):
    manager, clock = _make_manager(
        [_dumpsys(song="海阔天空", singer="Beyond", state=6),
         _dumpsys(song="海阔天空", singer="Beyond", state=3)],
        monkeypatch,
    )

    ready = manager.wait_for_playback_ready()

    assert ready is True
    assert manager.driver.calls == 2
    # The final sleep after state=3 verification is the audio settling delay.
    assert clock.sleeps[-1] == 0.3
    assert manager.logger.warnings == []


def test_wait_for_playback_ready_rejects_stale_song_metadata(monkeypatch):
    manager, _clock = _make_manager(
        # state=3 but the previous track is still reported → not ready yet.
        [_dumpsys(song="真的爱你", singer="Beyond", state=3),
         _dumpsys(song="海阔天空", singer="Beyond", state=3)],
        monkeypatch,
    )

    ready = manager.wait_for_playback_ready(expected_song="海阔天空")

    assert ready is True
    assert manager.driver.calls == 2


def test_wait_for_playback_ready_matches_search_query_against_reported_title(monkeypatch):
    # Callers pass the original request ("歌名 歌手"); MediaSession reports the title only.
    manager, _clock = _make_manager(
        [_dumpsys(song="似是故人来", singer="梅艳芳", state=3)],
        monkeypatch,
    )

    ready = manager.wait_for_playback_ready(expected_song="似是故人来 梅艳芳")

    assert ready is True
    assert manager.driver.calls == 1


def test_wait_for_playback_ready_keeps_polling_while_connecting(monkeypatch):
    manager, clock = _make_manager(
        [_dumpsys(song="海阔天空", state=8),   # Connecting
         _dumpsys(song="海阔天空", state=6),   # Buffering
         _dumpsys(song="海阔天空", state=3)],  # Playing
        monkeypatch,
    )

    ready = manager.wait_for_playback_ready(settling_delay=0.0)

    assert ready is True
    assert manager.driver.calls == 3
    assert clock.sleeps == [0.3, 0.3, 0.0]


def test_wait_for_playback_ready_times_out_with_warning_and_no_exception(monkeypatch):
    manager, clock = _make_manager(
        [_dumpsys(song="海阔天空", singer="Beyond", state=6)],  # stuck buffering forever
        monkeypatch,
    )

    ready = manager.wait_for_playback_ready(timeout=5.0)

    assert ready is False
    assert manager.logger.warnings, "timeout must log a warning"
    assert clock.now == pytest.approx(5.1, abs=0.31)
