import datetime as dt
from contextlib import asynccontextmanager

import pytest


class RuntimeStub:
    def emit(self, *args, **kwargs):
        return None

    @asynccontextmanager
    async def ui_session(self, *_args, **_kwargs):
        yield


class HandlerStub:
    def __init__(self, config: dict):
        self.config = config

        class _Logger:
            def info(self, *_a, **_k):
                return None

            def error(self, *_a, **_k):
                return None

        self.logger = _Logger()


class MessageInfoStub:
    def __init__(self, nickname: str, content: str = ":play"):
        self.nickname = nickname
        self.content = content


class DummyCommand:
    def __init__(self):
        self.called = False

    async def process(self, *_args, **_kwargs):
        self.called = True
        return {"message": "OK"}


@pytest.fixture(autouse=True)
def _reset_sleep_singleton():
    from ushareiplay.managers.sleep_manager import SleepManager

    SleepManager.reset_for_tests()
    yield
    SleepManager.reset_for_tests()


@pytest.fixture
def _patch_user_dao(monkeypatch):
    from ushareiplay.dal import user_dao as user_dao_module

    class _User:
        level = 1

    async def _get_or_create(_nickname: str):
        return _User()

    monkeypatch.setattr(user_dao_module.UserDAO, "get_or_create", staticmethod(_get_or_create))


def _make_command_manager(config: dict):
    from ushareiplay.managers.command_manager import CommandManager

    cm = CommandManager.instance()
    cm._handler = HandlerStub(config)
    cm.configure_runtime(RuntimeStub())
    return cm


@pytest.mark.asyncio
async def test_normal_user_all_day_window_blocked_play_is_intercepted(_patch_user_dao):
    cm = _make_command_manager(
        {
            "system_users": ["Timer"],
            "sleep": {
                "enabled": True,
                "start": "00:00",
                "end": "00:00",  # all day
                "blocked_commands": ["play"],
            },
        }
    )
    cmd = DummyCommand()
    msg = MessageInfoStub("alice", ":play")
    command_info = {
        "prefix": "play",
        "parameters": [],
        "level": 1,
        "error_template": "{error}",
        "response_template": "{message}",
    }

    res = await cm.process_command(cmd, msg, command_info)

    assert cmd.called is False
    assert "睡眠守护已开启" in (res or "")
    assert "00:00-00:00" in res
    assert ":sleep off" in res


@pytest.mark.asyncio
async def test_timer_user_is_allowed_even_when_blocked(_patch_user_dao):
    cm = _make_command_manager(
        {
            "system_users": ["Timer"],
            "sleep": {
                "enabled": True,
                "start": "00:00",
                "end": "00:00",  # all day
                "blocked_commands": ["play"],
            },
        }
    )
    cmd = DummyCommand()
    msg = MessageInfoStub("Timer", ":play")
    command_info = {
        "prefix": "play",
        "parameters": [],
        "level": 1,
        "error_template": "{error}",
        "response_template": "{message}",
    }

    res = await cm.process_command(cmd, msg, command_info)

    assert cmd.called is True
    assert "OK @Timer" == res


@pytest.mark.asyncio
async def test_normal_user_prefix_not_blocked_is_allowed(_patch_user_dao):
    cm = _make_command_manager(
        {
            "system_users": ["Timer"],
            "sleep": {
                "enabled": True,
                "start": "00:00",
                "end": "00:00",  # all day
                "blocked_commands": ["play"],
            },
        }
    )
    cmd = DummyCommand()
    msg = MessageInfoStub("alice", ":pause")
    command_info = {
        "prefix": "pause",
        "parameters": [],
        "level": 1,
        "error_template": "{error}",
        "response_template": "{message}",
    }

    res = await cm.process_command(cmd, msg, command_info)

    assert cmd.called is True
    assert "OK @alice" == res


@pytest.mark.asyncio
async def test_enabled_false_does_not_intercept(_patch_user_dao):
    cm = _make_command_manager(
        {
            "system_users": ["Timer"],
            "sleep": {
                "enabled": False,
                "start": "00:00",
                "end": "00:00",  # all day, but disabled
                "blocked_commands": ["play"],
            },
        }
    )
    cmd = DummyCommand()
    msg = MessageInfoStub("alice", ":play")
    command_info = {
        "prefix": "play",
        "parameters": [],
        "level": 1,
        "error_template": "{error}",
        "response_template": "{message}",
    }

    res = await cm.process_command(cmd, msg, command_info)

    assert cmd.called is True
    assert "OK @alice" == res


@pytest.mark.asyncio
async def test_outside_window_does_not_intercept(_patch_user_dao, monkeypatch):
    # Window 23:00-06:00; freeze "now" at 12:00 so it is outside window.
    from ushareiplay.managers import sleep_manager as sg_module

    class _FixedDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 5, 8, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(sg_module.dt, "datetime", _FixedDatetime)

    cm = _make_command_manager(
        {
            "system_users": ["Timer"],
            "sleep": {
                "enabled": True,
                "start": "23:00",
                "end": "06:00",
                "blocked_commands": ["play"],
            },
        }
    )
    cmd = DummyCommand()
    msg = MessageInfoStub("alice", ":play")
    command_info = {
        "prefix": "play",
        "parameters": [],
        "level": 1,
        "error_template": "{error}",
        "response_template": "{message}",
    }

    res = await cm.process_command(cmd, msg, command_info)

    assert cmd.called is True
    assert "OK @alice" == res

