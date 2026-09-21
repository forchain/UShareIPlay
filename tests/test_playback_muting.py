"""Ticket #299: PlaybackMuting lifecycle coordinator and configuration schema.

Observes the muting contract from the outside: the ordering of the mute click,
the caller's playback work, the MediaSession readiness wait, and the guaranteed
microphone restore — plus the guest-room bypass policy.
"""

import pytest

from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.state.room_state import RoomState


class _Logger:
    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []

    def info(self, msg, *args):
        self.infos.append(msg % args if args else msg)

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def error(self, msg, *args):
        self.errors.append(msg % args if args else msg)


class _ElementFinder:
    def __init__(self, desc, present):
        self.desc = desc
        self.present = present

    def try_find_element(self, _key, log=True):
        return object() if self.present else None

    def try_get_attribute(self, _element, _attribute):
        return self.desc


class _KeyActions:
    def switch_to_app(self):
        return True


class _SoulHandler:
    def __init__(self, events, desc="闭麦按钮", mic_present=True, config=None):
        self.events = events
        self.config = config if config is not None else {}
        self.logger = _Logger()
        self.key_actions = _KeyActions()
        self.element_finder = _ElementFinder(desc, mic_present)

    def ensure_mic_active(self):
        self.events.append("restore")


class _MusicManager:
    def __init__(self, events, ready=True):
        self.events = events
        self.ready = ready
        self.readiness_calls = []

    def wait_for_playback_ready(self, expected_song=None, timeout=5.0, settling_delay=0.3):
        self.readiness_calls.append((expected_song, timeout, settling_delay))
        self.events.append(f"wait:{expected_song}")
        return self.ready


class _MicManager:
    def __init__(self, events):
        self.events = events

    def toggle_mic(self, enable):
        self.events.append(f"mute:{enable}")
        return {"state": "关闭" if not enable else "开启"}


def _make_coordinator(desc="闭麦按钮", mic_present=True, config=None, ready=True):
    events = []
    coordinator = PlaybackMuting.__new__(PlaybackMuting)
    coordinator.soul_handler = _SoulHandler(events, desc, mic_present, config)
    coordinator.music_manager = _MusicManager(events, ready)
    coordinator.mic_manager = _MicManager(events)
    coordinator.logger = coordinator.soul_handler.logger
    return coordinator, events


def _set_guest_room(is_guest: bool):
    RoomState.reset_instance()
    RoomState.initialize().is_guest_room = is_guest


# --------------------------------------------------------------------------
# Standard lifecycle
# --------------------------------------------------------------------------

def test_guard_mutes_then_waits_for_readiness_then_restores_mic():
    coordinator, events = _make_coordinator()

    with coordinator.guard(expected_song="海阔天空") as muted:
        events.append("playback")

    assert muted is True
    assert events == ["mute:False", "playback", "wait:海阔天空", "restore"]
    assert coordinator.music_manager.readiness_calls == [("海阔天空", 5.0, 0.3)]


def test_guard_skips_mute_click_when_mic_is_already_off():
    coordinator, events = _make_coordinator(desc="开麦按钮")

    with coordinator.guard() as muted:
        events.append("playback")

    assert muted is False
    assert events == ["playback", "wait:None", "restore"]


def test_guard_skips_mute_click_when_mic_button_is_absent():
    coordinator, events = _make_coordinator(mic_present=False)

    with coordinator.guard() as muted:
        events.append("playback")

    assert muted is False
    assert events == ["playback", "wait:None", "restore"]


# --------------------------------------------------------------------------
# Scope policy
# --------------------------------------------------------------------------

def test_guard_bypasses_muting_in_host_room_when_guest_room_only():
    _set_guest_room(False)
    coordinator, events = _make_coordinator(config={"playback_mute": {"guest_room_only": True}})

    with coordinator.guard(expected_song="晴天") as muted:
        events.append("playback")

    assert muted is False
    assert events == ["playback"]
    assert coordinator.music_manager.readiness_calls == []


def test_guard_engages_in_guest_room_when_guest_room_only():
    _set_guest_room(True)
    coordinator, events = _make_coordinator(config={"playback_mute": {"guest_room_only": True}})

    with coordinator.guard(expected_song="晴天") as muted:
        events.append("playback")

    assert muted is True
    assert events == ["mute:False", "playback", "wait:晴天", "restore"]


def test_guard_bypasses_everything_when_disabled():
    _set_guest_room(True)
    coordinator, events = _make_coordinator(config={"playback_mute": {"enabled": False}})

    with coordinator.guard(expected_song="晴天") as muted:
        events.append("playback")

    assert muted is False
    assert events == ["playback"]
    assert coordinator.music_manager.readiness_calls == []


# --------------------------------------------------------------------------
# Failure and timeout recovery
# --------------------------------------------------------------------------

def test_guard_restores_mic_and_skips_readiness_when_playback_raises():
    coordinator, events = _make_coordinator()

    with pytest.raises(RuntimeError, match="play failed"):
        with coordinator.guard(expected_song="海阔天空"):
            events.append("playback")
            raise RuntimeError("play failed")

    assert events == ["mute:False", "playback", "restore"]
    assert coordinator.music_manager.readiness_calls == []


def test_guard_restores_mic_when_readiness_times_out():
    coordinator, events = _make_coordinator(ready=False)

    with coordinator.guard(expected_song="海阔天空"):
        events.append("playback")

    assert events == ["mute:False", "playback", "wait:海阔天空", "restore"]
    assert coordinator.logger.warnings


# --------------------------------------------------------------------------
# Configuration schema
# --------------------------------------------------------------------------

def test_settings_fall_back_to_documented_defaults():
    coordinator, _events = _make_coordinator(config={})

    assert coordinator.settings == {
        "enabled": True,
        "guest_room_only": False,
        "timeout": 5.0,
        "settling_delay": 0.3,
    }


def test_settings_pass_configured_timeout_and_settling_delay_to_readiness_wait():
    coordinator, events = _make_coordinator(
        config={"playback_mute": {"timeout": 8.0, "settling_delay": 0.5}}
    )

    with coordinator.guard(expected_song="海阔天空"):
        events.append("playback")

    assert coordinator.music_manager.readiness_calls == [("海阔天空", 8.0, 0.5)]


def test_settings_ignore_unknown_keys():
    coordinator, _events = _make_coordinator(config={"playback_mute": {"unknown": 1}})

    assert coordinator.settings == {
        "enabled": True,
        "guest_room_only": False,
        "timeout": 5.0,
        "settling_delay": 0.3,
    }


def test_shipped_config_declares_playback_mute_defaults():
    from ushareiplay.core.config_loader import ConfigLoader

    config = ConfigLoader.load_config()

    assert config["soul"]["playback_mute"] == {
        "enabled": True,
        "guest_room_only": False,
        "timeout": 5.0,
        "settling_delay": 0.3,
    }
