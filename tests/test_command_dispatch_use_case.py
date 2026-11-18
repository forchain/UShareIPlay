"""Dispatch-command use case: level, sleep, guest-room, retry and silence.

The gates are pinned at the use-case seam with in-memory ports, independent of
CommandManager / Appium. The public-screen wording stays in the inbound adapter
and is covered by the existing CommandManager characterization tests.
"""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest

from ushareiplay.modules.command.domain import (
    CommandCatalogue,
    GuestRoomRestricted,
    InsufficientCommandLevel,
    SleepBlocked,
    UnknownCommand,
)
from ushareiplay.modules.command.use_cases import DispatchCommand
from ushareiplay.modules.shared.roles import RolePolicy


class FakeRuntime:
    def __init__(self):
        self.events = []
        self.sessions = []

    def emit(self, event, *, ctx):
        self.events.append((event, ctx))

    @asynccontextmanager
    async def ui_session(self, reason):
        self.sessions.append(reason)
        yield


class FakeClock:
    def __init__(self):
        self.sleeps = []

    def now(self):
        raise NotImplementedError

    async def sleep(self, seconds):
        self.sleeps.append(seconds)


class FakeUsers:
    def __init__(self, level=0):
        self.level = level
        self.lookups = []

    async def get_or_create(self, username):
        self.lookups.append(username)
        return SimpleNamespace(level=self.level)


class FakeSleep:
    def __init__(self, blocked=()):
        self.blocked = set(blocked)

    def is_blocked_command(self, command):
        return command in self.blocked


class FakeRoom:
    def __init__(self, is_guest_room=False, allowed=()):
        self.is_guest_room = is_guest_room
        self.allowed = set(allowed)

    def is_command_allowed_in_guest_room(self, prefix):
        return prefix in self.allowed


class FakeSilence:
    def __init__(self):
        self.calls = []

    @contextmanager
    def __call__(self, enabled):
        self.calls.append(enabled)
        yield


class Executable:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def process(self, message_info, parameters):
        self.calls.append(tuple(parameters))
        return self.results.pop(0)


def _policy():
    return RolePolicy(
        {
            "room_owner": "Joyer",
            "admin_users": ["Outlaw"],
            "system_users": ["Timer"],
        }
    )


def _message(nickname="Alice", **overrides):
    values = {
        "nickname": nickname,
        "content": ":play",
        "silent": False,
        "sleep_exempt": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _info(**overrides):
    values = {
        "prefix": "play",
        "parameters": [],
        "level": 0,
        "error_template": "错误: {error}",
        "response_template": "{message}",
    }
    values.update(overrides)
    return values


def _use_case(
    *,
    users=None,
    sleep=None,
    room=None,
    runtime=None,
    clock=None,
    silence=None,
    catalogue=None,
):
    return DispatchCommand(
        policy=_policy(),
        catalogue=catalogue,
        users=users or FakeUsers(),
        runtime=runtime or FakeRuntime(),
        clock=clock or FakeClock(),
        silence=silence or FakeSilence(),
        sleep=sleep,
        room=room,
    )


@pytest.mark.asyncio
async def test_insufficient_level_blocks_before_the_command_runs():
    runtime = FakeRuntime()
    users = FakeUsers(level=1)
    command = Executable({"message": "ok"})

    with pytest.raises(InsufficientCommandLevel) as caught:
        await _use_case(users=users, runtime=runtime).execute(
            command, _message(), _info(level=2)
        )

    assert (caught.value.required_level, caught.value.user_level) == (2, 1)
    assert command.calls == []
    assert [event[0] for event in runtime.events] == ["command.received"]


@pytest.mark.asyncio
async def test_privileged_user_skips_level_lookup_and_runs():
    users = FakeUsers(level=0)
    command = Executable({"message": "ok"})

    result = await _use_case(users=users).execute(
        command, _message("Joyer"), _info(level=9)
    )

    assert result == "ok @Joyer"
    assert users.lookups == []


@pytest.mark.asyncio
async def test_sleep_blocked_raises_and_does_not_run_the_command():
    command = Executable({"message": "ok"})

    with pytest.raises(SleepBlocked):
        await _use_case(sleep=FakeSleep({"play"})).execute(
            command, _message(), _info()
        )

    assert command.calls == []


@pytest.mark.asyncio
async def test_human_operator_bypasses_sleep_block():
    command = Executable({"message": "ok"})

    result = await _use_case(sleep=FakeSleep({"play"})).execute(
        command, _message("Joyer"), _info()
    )

    assert result == "ok @Joyer"
    assert command.calls == [()]


@pytest.mark.asyncio
async def test_sleep_exempt_message_bypasses_sleep_block():
    command = Executable({"message": "ok"})

    result = await _use_case(sleep=FakeSleep({"play"})).execute(
        command, _message(sleep_exempt=True), _info()
    )

    assert result == "ok @Alice"
    assert command.calls == [()]


@pytest.mark.asyncio
async def test_guest_room_restriction_blocks_disallowed_command():
    command = Executable({"message": "ok"})

    with pytest.raises(GuestRoomRestricted):
        await _use_case(room=FakeRoom(is_guest_room=True)).execute(
            command, _message(), _info(prefix="theme")
        )

    assert command.calls == []


@pytest.mark.asyncio
async def test_guest_room_allows_whitelisted_command():
    command = Executable({"message": "ok"})

    result = await _use_case(
        room=FakeRoom(is_guest_room=True, allowed={"play"})
    ).execute(command, _message(), _info())

    assert result == "ok @Alice"
    assert command.calls == [()]


@pytest.mark.asyncio
async def test_retry_reexecutes_once_after_an_error():
    runtime = FakeRuntime()
    clock = FakeClock()
    command = Executable({"error": "boom"}, {"message": "ok"})

    result = await _use_case(runtime=runtime, clock=clock).execute(
        command, _message(), _info(retry=True)
    )

    assert result == "ok @Alice"
    assert len(command.calls) == 2
    assert clock.sleeps == [0.5]
    assert [event[0] for event in runtime.events].count("command.retry") == 1


@pytest.mark.asyncio
async def test_retry_disabled_runs_once_and_renders_the_error():
    command = Executable({"error": "boom"})

    result = await _use_case().execute(command, _message(), _info(retry=False))

    assert result == "错误: boom"
    assert command.calls == [()]


@pytest.mark.asyncio
async def test_execution_runs_inside_command_silence_and_ui_session():
    runtime = FakeRuntime()
    silence = FakeSilence()

    await _use_case(runtime=runtime, silence=silence).execute(
        Executable({"message": "ok"}), _message(silent=True), _info()
    )

    assert silence.calls == [True]
    assert runtime.sessions == ["command:play"]
    assert [event[0] for event in runtime.events] == [
        "command.received",
        "command.dispatch",
        "command.result",
    ]


@pytest.mark.asyncio
async def test_response_template_defaults_the_missing_release_date():
    command = Executable({"song": "晴天"})

    result = await _use_case().execute(
        command, _message(), _info(response_template="{song} {release_date}")
    )

    assert result == "晴天  @Alice"


@pytest.mark.asyncio
async def test_unknown_command_is_a_domain_error():
    with pytest.raises(UnknownCommand) as caught:
        await _use_case().execute(None, _message(), _info())

    assert caught.value.prefix == "play"


@pytest.mark.asyncio
async def test_catalogue_subcommand_level_takes_precedence():
    catalogue = CommandCatalogue.from_config(
        {
            "commands": [
                {
                    "prefix": "playlist",
                    "level": 2,
                    "subcommands": {"": {"level": 1}, "*": {"level": 2}},
                }
            ]
        }
    )
    users = FakeUsers(level=1)
    command = Executable({"message": "ok"})

    with pytest.raises(InsufficientCommandLevel) as caught:
        await _use_case(users=users, catalogue=catalogue).execute(
            command,
            _message(),
            _info(prefix="playlist", parameters=["欧美流行"]),
        )

    assert caught.value.required_level == 2
    assert command.calls == []
