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

from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.models.message_info import MessageInfo


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

    def send_for_message_info(self, message_info, response, silent=False):
        self.events.append(f"notify:{response}")


class _DispatchStub:
    recorder = None

    @classmethod
    def instance(cls):
        return cls.recorder


class _ElementFinder:
    def try_find_element(self, _key, log=True):
        return object()

    def try_get_attribute(self, _element, _attribute):
        return "闭麦按钮"


class _SoulHandler:
    def __init__(self, events):
        self.events = events
        self.logger = _Logger()
        self.config = {}
        self.key_actions = SimpleNamespace(switch_to_app=lambda: True)
        self.element_finder = _ElementFinder()

    def ensure_mic_active(self):
        self.events.append("restore")


class _MusicManager:
    def __init__(self, events):
        self.events = events

    def wait_for_playback_ready(self, expected_song=None, timeout=5.0, settling_delay=0.3):
        self.events.append(f"wait:{expected_song}")
        return True


class _MicManager:
    def __init__(self, events):
        self.events = events

    def toggle_mic(self, enable):
        self.events.append(f"mute:{enable}")
        return {"state": "关闭"}


class _PlaybackCommand:
    """Stands in for :play / :next / :skip and friends."""

    playback_muting = True

    def __init__(self, events, expected_from_parameters=True):
        self.events = events
        self.expected_from_parameters = expected_from_parameters

    async def process(self, message_info, parameters):
        self.events.append("playback")
        return {"song": "海阔天空", "singer": "Beyond", "album": "乐与怒"}

    def playback_expected_song(self, parameters):
        if not self.expected_from_parameters:
            return None
        return " ".join(parameters)


class _FailingPlaybackCommand(_PlaybackCommand):
    """A playback command whose search came back empty or VIP-blocked."""

    async def process(self, message_info, parameters):
        self.events.append("playback")
        return {"error": "Song not found"}


class _PlainCommand:
    """Stands in for a non-playback command such as :info."""

    playback_muting = False

    def __init__(self, events):
        self.events = events

    async def process(self, message_info, parameters):
        self.events.append("playback")
        return {"message": "ok"}


def _make_coordinator(events):
    coordinator = PlaybackMuting.__new__(PlaybackMuting)
    coordinator.logger = _Logger()
    coordinator.soul_handler = _SoulHandler(events)
    coordinator.music_manager = _MusicManager(events)
    coordinator.mic_manager = _MicManager(events)
    return coordinator


def _make_manager(monkeypatch, command, coordinator):
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    _DispatchStub.recorder = _Recorder(coordinator.soul_handler.events)
    monkeypatch.setattr("ushareiplay.managers.command_manager.MessageDispatch", _DispatchStub)
    monkeypatch.setattr(PlaybackMuting, "instance", staticmethod(lambda: coordinator))
    manager.configure_runtime(_Runtime())
    manager._logger = _Logger()
    manager._handler = SimpleNamespace(config={"system_users": ["Console"]})
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


def test_playback_command_mutes_notifies_waits_then_restores_mic(monkeypatch):
    coordinator = _make_coordinator([])
    events = coordinator.soul_handler.events
    manager = _make_manager(monkeypatch, _PlaybackCommand(events), coordinator)

    asyncio.run(
        manager.execute_command_messages([MessageInfo(content=":play 海阔天空", nickname="Console")])
    )

    assert events == [
        "screen",
        "mute:False",
        "playback",
        "notify:海阔天空 - Beyond @Console",
        "wait:海阔天空",
        "restore",
    ]


def test_failed_playback_restores_mic_without_waiting_for_readiness(monkeypatch):
    """User story 11: a not-found or VIP-blocked request returns the mic at once."""
    coordinator = _make_coordinator([])
    events = coordinator.soul_handler.events
    manager = _make_manager(monkeypatch, _FailingPlaybackCommand(events), coordinator)

    asyncio.run(
        manager.execute_command_messages([MessageInfo(content=":play 不存在", nickname="Console")])
    )

    assert events == [
        "screen",
        "mute:False",
        "playback",
        "notify:Failed to play music, because Song not found",
        "restore",
    ]


def test_non_playback_command_leaves_microphone_untouched(monkeypatch):
    coordinator = _make_coordinator([])
    events = coordinator.soul_handler.events
    manager = _make_manager(monkeypatch, _PlainCommand(events), coordinator)

    asyncio.run(
        manager.execute_command_messages([MessageInfo(content=":info", nickname="Console")])
    )

    assert events == ["screen", "playback", "notify:ok @Console"]


def test_playback_command_without_expected_song_still_guards_microphone(monkeypatch):
    coordinator = _make_coordinator([])
    events = coordinator.soul_handler.events
    command = _PlaybackCommand(events, expected_from_parameters=False)
    manager = _make_manager(monkeypatch, command, coordinator)

    asyncio.run(
        manager.execute_command_messages([MessageInfo(content=":skip", nickname="Console")])
    )

    assert events == [
        "screen",
        "mute:False",
        "playback",
        "notify:海阔天空 - Beyond @Console",
        "wait:None",
        "restore",
    ]


# --------------------------------------------------------------------------
# Declarations on the real command classes
# --------------------------------------------------------------------------

PLAYBACK_COMMANDS = [
    ("play", "PlayCommand"),
    ("next", "NextCommand"),
    ("skip", "SkipCommand"),
    ("playlist", "PlaylistCommand"),
    ("album", "AlbumCommand"),
    ("singer", "SingerCommand"),
    ("fav", "FavCommand"),
    ("radio", "RadioCommand"),
]


@pytest.mark.parametrize("module_name,class_name", PLAYBACK_COMMANDS)
def test_playback_commands_declare_muting_participation(module_name, class_name):
    module = importlib.import_module(f"ushareiplay.commands.{module_name}")
    command_class = getattr(module, class_name)

    assert command_class.playback_muting is True
    assert not hasattr(command_class, "requires_mic")


@pytest.mark.parametrize("module_name,class_name", PLAYBACK_COMMANDS)
def test_playback_commands_leave_mic_activation_to_the_coordinator(module_name, class_name):
    """An inline ensure_mic_active() re-opens the mic mid-playback, undoing the guard mute."""
    module_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ushareiplay"
        / "commands"
        / f"{module_name}.py"
    )

    source = module_path.read_text(encoding="utf-8")

    assert "ensure_mic_active" not in source


def test_play_command_reports_requested_song_for_readiness_check():
    from ushareiplay.commands.play import PlayCommand

    command = PlayCommand.__new__(PlayCommand)

    assert command.playback_expected_song(["海阔天空", "Beyond"]) == "海阔天空 Beyond"
    assert command.playback_expected_song([]) is None
    assert command.playback_expected_song(["?"]) is None


def test_base_command_does_not_participate_in_muting_by_default():
    from ushareiplay.core.base_command import BaseCommand

    assert BaseCommand.playback_muting is False
    assert not hasattr(BaseCommand, "requires_mic")
