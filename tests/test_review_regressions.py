"""Regression tests for the review findings fixed in this change set.

Each test pins the *observable behaviour* the review said was broken:
auto-end treating error dicts as success, missing error_template crashes,
the console thread spinning on EOF, the DB dir following cwd, prefix
false-positives, non-atomic status writes, missed repeat timers, a bare
string in `admin_users`, and commas inside song titles.
"""

import json
import queue
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from ushareiplay.core.command_parser import CommandParser
from ushareiplay.core.observability import Observability
from ushareiplay.core.roles import RolePolicy, _normalize_set


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


# ---------------------------------------------------------------------------
# 1 + 2: PartyManager.update() — error dict is a failure, success marks the day
# ---------------------------------------------------------------------------


@pytest.fixture
def party_manager(monkeypatch):
    from ushareiplay.managers.party_manager import PartyManager
    from ushareiplay.state.room_state import RoomState

    manager = PartyManager.instance()
    manager._handler = SimpleNamespace(config={}, logger=_Logger())
    manager._logger = _Logger()
    manager.init_time = datetime.now() - timedelta(minutes=800)
    manager.trigger_minutes = 720
    monkeypatch.setattr(RoomState, "in_guest_room", classmethod(lambda cls: False))
    monkeypatch.setattr(manager, "get_party_user_count", lambda: 1)
    return manager


def test_auto_end_error_dict_keeps_timers(monkeypatch, party_manager):
    resets = []
    calls = []
    monkeypatch.setattr(
        party_manager,
        "end_party",
        lambda: calls.append(1) or {"error": "Failed to switch to Soul app"},
    )
    monkeypatch.setattr(party_manager, "reset_party_time", lambda: resets.append(1))

    party_manager.update()

    # An error dict is a failure: no success log, no timer reset ...
    assert resets == []
    # ... and the attempt still counts for the once-a-day guard, so the next
    # chat batch does not hammer the end-party UI again.
    assert party_manager.last_auto_end_date == date.today()

    party_manager.init_time = datetime.now() - timedelta(minutes=800)
    party_manager.update()
    assert len(calls) == 1


def test_auto_end_success_marks_date_and_blocks_second_run(monkeypatch, party_manager):
    resets = []
    calls = []
    monkeypatch.setattr(party_manager, "end_party", lambda: calls.append(1) or {"success": "Party ended"})
    monkeypatch.setattr(party_manager, "reset_party_time", lambda: resets.append(1))

    party_manager.update()
    assert resets == [1]
    assert party_manager.last_auto_end_date == date.today()

    # Same day, timer already due again: the once-a-day guard must stop it.
    party_manager.init_time = datetime.now() - timedelta(minutes=800)
    party_manager.update()
    assert len(calls) == 1
    assert resets == [1]


# ---------------------------------------------------------------------------
# 3: Permission / sleep rejections without a usable error_template
# ---------------------------------------------------------------------------


class _User:
    level = 0


class _Runtime:
    def emit(self, *_args, **_kwargs):
        return None


class _Handler:
    def __init__(self, config):
        self.config = config
        self.logger = _Logger()


class _Msg:
    def __init__(self, nickname="alice", content="help", sleep_exempt=False):
        self.nickname = nickname
        self.content = content
        self.sleep_exempt = sleep_exempt


class _DummyCommand:
    def __init__(self):
        self.called = False

    async def process(self, *_args, **_kwargs):
        self.called = True
        return {"message": "OK"}


@pytest.fixture
def command_manager(monkeypatch):
    from ushareiplay.core.message_dispatch import MessageDispatch
    from ushareiplay.dal import user_dao as user_dao_module
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.sleep_manager import SleepManager

    config = {
        "room_owner": "Joyer",
        "admin_users": ["Outlier"],
        "system_users": ["Timer", "Agent"],
        "sleep": {
            "enabled": True,
            "start": "00:00",
            "end": "00:00",  # all day
            "blocked_commands": ["help"],
        },
    }

    async def _get_or_create(_nickname):
        return _User()

    monkeypatch.setattr(user_dao_module.UserDAO, "get_or_create", staticmethod(_get_or_create))

    SleepManager.initialize(config)
    manager = CommandManager.instance()
    manager._handler = _Handler(config)
    manager.configure_runtime(_Runtime())
    return manager


@pytest.mark.asyncio
async def test_permission_rejection_without_error_template_uses_error_fallback(command_manager):
    command_info = {"prefix": "help", "parameters": [], "level": 9}

    res = await command_manager.process_command(_DummyCommand(), _Msg(), command_info)

    assert res is not None
    assert "需要等级 9" in res


@pytest.mark.asyncio
async def test_permission_rejection_without_parameters_fills_party_id(command_manager):
    command_info = {
        "prefix": "room",
        "parameters": [],
        "level": 9,
        "error_template": "Failed to join party {party_id}, because {error}",
    }

    res = await command_manager.process_command(_DummyCommand(), _Msg(content="room"), command_info)

    assert res is not None
    assert "party unknown" in res


@pytest.mark.asyncio
async def test_sleep_rejection_without_error_template_still_blocks(command_manager):
    command_info = {"prefix": "help", "parameters": [], "level": 0}
    command = _DummyCommand()

    res = await command_manager.process_command(command, _Msg(nickname="alice"), command_info)

    assert "休息中" in (res or "")
    assert command.called is False


# ---------------------------------------------------------------------------
# 4: Console input thread exits on EOF instead of spinning
# ---------------------------------------------------------------------------


def test_console_input_stops_on_eof(monkeypatch):
    from ushareiplay.core.app_controller import AppController

    controller = AppController.__new__(AppController)
    controller.is_running = True
    controller.in_console_mode = False
    controller.input_queue = queue.Queue()
    controller.logger = _Logger()

    attempts = []

    def _eof(_prompt=""):
        attempts.append(1)
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)

    controller._console_input()

    assert len(attempts) == 1
    assert controller.is_running is True


# ---------------------------------------------------------------------------
# 5: DatabaseManager anchors the data dir at the repo root, not the caller cwd
# ---------------------------------------------------------------------------


def test_database_manager_uses_repo_root_data_dir(tmp_path, monkeypatch):
    from ushareiplay.core.db_manager import DatabaseManager
    from ushareiplay.core.paths import repo_root

    elsewhere = tmp_path / "not-the-repo"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    manager = DatabaseManager()

    db_path = Path(manager.db_url.removeprefix("sqlite://"))
    assert db_path.parent == repo_root() / "data"
    assert db_path.parent != elsewhere / "data"


# ---------------------------------------------------------------------------
# 9: is_valid_command matches whole prefixes, not substrings
# ---------------------------------------------------------------------------


def test_is_valid_command_requires_exact_first_token():
    parser = CommandParser([{"prefix": "play"}, {"prefix": "playlist"}])

    assert parser.is_valid_command("play 稻香") is True
    assert parser.is_valid_command("PLAY 稻香") is True
    assert parser.is_valid_command("  playlist") is True
    assert parser.is_valid_command("players sing") is False
    assert parser.is_valid_command("replay") is False


# ---------------------------------------------------------------------------
# 10: status.json is replaced atomically (no leftover temp, always valid JSON)
# ---------------------------------------------------------------------------


def test_write_status_replaces_atomically(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("logging:\n  directory: logs\n", encoding="utf-8")
    (tmp_path / "src").mkdir()

    obs = Observability(run_id="atomic-run")
    status_path = obs.write_status({"foreground_app": "Soul"})

    assert not status_path.with_suffix(status_path.suffix + ".tmp").exists()
    assert json.loads(status_path.read_text(encoding="utf-8"))["run_id"] == "atomic-run"


# ---------------------------------------------------------------------------
# 11: a repeat timer that missed downtime fires once, not once per missed day
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeat_timer_advances_past_missed_days(monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.timer_manager import TimerManager
    from ushareiplay.dal.timer_dao import TimerDAO

    manager = TimerManager.instance()
    manager._logger = _Logger()
    manager._paused = False

    async def _put_message(_message_info):
        return True

    monkeypatch.setattr(MessageQueue.instance(), "put_message", _put_message)

    scheduled = {}

    async def _update_next_trigger(key, next_trigger):
        scheduled[key] = next_trigger
        return True

    monkeypatch.setattr(TimerDAO, "update_next_trigger", staticmethod(_update_next_trigger))

    stale = datetime.now() - timedelta(days=3)
    await manager._trigger_timer(
        "daily",
        {"message": "daily hello", "repeat": True, "next_trigger": stale.isoformat()},
    )

    assert "daily" in scheduled
    assert scheduled["daily"] > datetime.now()
    assert scheduled["daily"] - stale >= timedelta(days=3)


# ---------------------------------------------------------------------------
# 12: a bare YAML scalar is one name, not a sequence of characters
# ---------------------------------------------------------------------------


def test_normalize_set_treats_bare_string_as_one_name():
    assert _normalize_set("Outlier") == {"outlier"}
    assert _normalize_set(["Outlier", "Joy"]) == {"outlier", "joy"}
    assert _normalize_set(None) == set()


def test_string_admin_users_do_not_grant_single_letter_admins():
    policy = RolePolicy({"admin_users": "Outlier", "room_owner": "Joyer"})

    assert policy.is_admin("Outlier") is True
    assert policy.is_admin("o") is False
    assert policy.is_admin("u") is False


# ---------------------------------------------------------------------------
# 14: commas inside song titles must not shift singer/album
# ---------------------------------------------------------------------------


class _DumpsysDriver:
    def __init__(self, output):
        self.output = output

    def execute_script(self, _script, _args=None):
        return self.output


def test_song_title_with_comma_keeps_album_field():
    from ushareiplay.managers.music_manager import MusicManager

    manager = MusicManager.__new__(MusicManager)
    manager.logger = _Logger()
    manager.music_handler = SimpleNamespace()
    manager.driver = _DumpsysDriver(
        "  metadata: size=48, description=Hello, Goodbye, The Beatles, Abbey Road\n"
        "  state=PlaybackState {state=6, position=1000, buffered position=0}\n"
    )

    info = manager.get_current_song_info()

    assert info["song"] == "Hello"
    assert info["singer"] == "Goodbye"
    # The remainder stays together instead of being dropped at the third comma.
    assert info["album"] == "The Beatles, Abbey Road"
