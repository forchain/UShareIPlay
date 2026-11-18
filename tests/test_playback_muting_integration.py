"""Ticket #300: playback commands run inside the PlaybackMuting lifecycle.

Drives the real CommandManager command path (parse -> process_command -> room
notification) with the real PlaybackMuting coordinator over a stubbed device
layer, and observes the whole sequence from outside:
mute -> playback -> chat notification -> media readiness -> unmute.
"""

import asyncio
import importlib
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
from ushareiplay.modules.playback.use_cases import PlaybackMuting
from ushareiplay.modules.shared.message_info import MessageInfo
from ushareiplay.modules.shared.config import ConfigSectionView


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _Runtime:
    def emit(self, *_args, **_kwargs):
        pass

    @asynccontextmanager
    async def ui_session(self, _reason):
        yield


class _Recorder:
    """Stands in for MessageDispatch and records room notifications."""

    def __init__(self, events):
        self.events = events

    def configure_runtime(self, _runtime):
        pass

    def bind_handler(self, _handler):
        return self

    def send_screen_message(self, message, silent=False):
        # The "[time] cmd ..." progress indicator; recorded opaquely.
        self.events.append("screen")

    async def send_for_message_info(self, message_info, response, silent=False):
        self.events.append(f"notify:{response}")


class _SoulHandler:
    """PlaybackMuting 只从 SoulHandler 取 logger 与 playback_mute 配置。"""

    def __init__(self, events):
        self.events = events
        self.logger = _Logger()
        self.config = ConfigSectionView("soul", {})


class _MusicManager:
    def __init__(self, events):
        self.events = events

    def wait_for_playback_ready(self, expected_song=None, timeout=5.0, settling_delay=0.3):
        self.events.append(f"wait:{expected_song}")
        return True


class _MicManager:
    def __init__(self, events):
        self.events = events

    def state(self):
        return True

    def set_active(self, enable):
        self.events.append(f"mute:{enable}")
        return {"state": "0" if not enable else "1"}

    def ensure_active(self):
        self.events.append("restore")
        return {"state": "1"}


def _make_coordinator(events):
    coordinator = PlaybackMuting.__new__(PlaybackMuting)
    coordinator.logger = _Logger()
    coordinator.soul_handler = _SoulHandler(events)
    coordinator.music_manager = _MusicManager(events)
    coordinator.mic_manager = _MicManager(events)
    return coordinator


def _make_manager(monkeypatch, command, coordinator):
    manager = CommandManager.__new__(CommandManager)
    manager.__init__(
        message_dispatch=_Recorder(coordinator.soul_handler.events)
    )
    manager.configure_runtime(_Runtime())
    manager._logger = _Logger()
    manager._handler = SimpleNamespace(
        config=ConfigSectionView("soul", {"system_users": ["Console"]})
    )
    monkeypatch.setattr(manager, "is_valid_command", lambda _content: True)
    monkeypatch.setattr(
        manager,
        "parse_command",
        lambda _content: {
            "prefix": "play",
            "level": 0,
            "parameters": ["海阔天空"],
            "response_template": "{song} - {singer}",
            "error_template": "Failed to play music, because {error}",
        },
    )
    monkeypatch.setattr(manager, "get_command", lambda _prefix: command)
    return manager


PLAYBACK_COMMANDS = [
    ("play", "PlayCommand"),
    ("playlist", "PlaylistCommand"),
    ("radio", "RadioCommand"),
    ("album", "AlbumCommand"),
    ("singer", "SingerCommand"),
    ("fav", "FavCommand"),
    ("skip", "SkipCommand"),
    ("next", "NextCommand"),
]


@pytest.mark.parametrize("module_name,class_name", PLAYBACK_COMMANDS)
def test_playback_commands_declare_no_command_level_muting(module_name, class_name):
    """ADR-0007：麦克风生命周期只归 `MusicManager`，命令层不再声明静音钩子。"""
    module = importlib.import_module(f"ushareiplay.adapters.inbound.chat.{module_name}")
    command_class = getattr(module, class_name)

    assert not hasattr(command_class, "playback_muting")
    assert not hasattr(command_class, "playback_muting_applies")
    assert not hasattr(command_class, "playback_expected_song")
    assert not hasattr(command_class, "requires_mic")


def test_skip_command_delegates_guard_and_mute_to_the_engine():
    """:skip 的守护与闭麦都在 `MusicManager.skip()`，命令层只转发请求者。"""
    import inspect
    from ushareiplay.adapters.inbound.chat.skip import SkipCommand

    source = inspect.getsource(SkipCommand.do_process)
    assert "self.controller.skip_song.execute(" in source
    assert "PlaybackMuting" not in source
    assert "guard_switch" not in source


def test_playback_commands_leave_mic_activation_to_the_coordinator():
    """Mic work declared inline in a playback command re-opens the mic mid-playback,
    undoing the guard mute — the microphone belongs to PlaybackMuting + MicControl."""
    for module_name, _class_name in PLAYBACK_COMMANDS:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "ushareiplay"
            / "adapters"
            / "inbound"
            / "chat"
            / f"{module_name}.py"
        )
        source = module_path.read_text(encoding="utf-8")
        for mic_api in ("ensure_mic_active", "ensure_active", "set_active", "toggle_mic"):
            assert mic_api not in source, f"{module_name} declares inline mic work"


def test_base_command_declares_no_muting_hooks():
    from ushareiplay.adapters.inbound.chat.base_command import BaseCommand

    assert not hasattr(BaseCommand, "playback_muting")
    assert not hasattr(BaseCommand, "playback_expected_song")
    assert not hasattr(BaseCommand, "playback_muting_applies")
    assert not hasattr(BaseCommand, "requires_mic")


class _NextMusicHandler:
    """Stands in for QQMusicHandler on the :next path."""

    def __init__(self, events):
        self.events = events

    def play_next(self, query):
        self.events.append(f"queue:{query}")
        return {"song": "海阔天空", "singer": "Beyond", "album": "乐与怒"}


def test_next_command_leaves_microphone_untouched(monkeypatch):
    """Ticket #319: driving the real NextCommand never mutes or restores the mic."""
    from ushareiplay.adapters.inbound.chat.next import NextCommand
    from ushareiplay.modules.playback.use_cases import PlayNext, PlaylistSession

    coordinator = _make_coordinator([])
    events = coordinator.soul_handler.events
    next_handler = _NextMusicHandler(events)
    controller = SimpleNamespace(
        soul_handler=coordinator.soul_handler,
        music_handler=next_handler,
        play_next=PlayNext(next_driver=next_handler, playlist_session=PlaylistSession()),
    )
    manager = _make_manager(monkeypatch, NextCommand(controller), coordinator)

    asyncio.run(
        manager.execute_command_messages([MessageInfo(content=":next 海阔天空", nickname="Console")])
    )

    assert events == ["screen", "queue:海阔天空", "notify:海阔天空 - Beyond @Console"]
