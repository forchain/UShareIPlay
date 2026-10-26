"""子命令级权限等级解析（issue #465）。

配置形态（config.yaml 的 commands 段）：

    - prefix: "playlist"
      level: 2
      subcommands:
        '':
          level: 1
        '*':
          level: 2

`''` 命中无参调用，具名 key 命中首参数（忽略大小写），`'*'` 命中其余带参调用；
都没命中时回退顶层 `level`。
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ushareiplay.core.command_parser import resolve_command_level


class RuntimeStub:
    def emit(self, *args, **kwargs):
        return None

    @asynccontextmanager
    async def ui_session(self, *_args, **_kwargs):
        yield


class HandlerStub:
    def __init__(self, config: dict):
        self.config = config
        self.logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            debug=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        self.controller = None


class MessageInfoStub:
    def __init__(self, nickname: str, content: str):
        self.nickname = nickname
        self.content = content
        self.sleep_exempt = False


class DummyCommand:
    def __init__(self):
        self.called = False

    async def process(self, *_args, **_kwargs):
        self.called = True
        return {"message": "OK"}


@pytest.fixture(autouse=True)
def _reset_singletons():
    from ushareiplay.core.message_dispatch import MessageDispatch
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.seat_manager import SeatManager
    from ushareiplay.state.room_state import RoomState

    CommandManager.reset_instance()
    MessageDispatch.reset_instance()
    MessageDispatch.initialize()
    RoomState.reset_instance()
    SeatManager.reset_instance()
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    yield
    CommandManager.reset_instance()
    MessageDispatch.reset_instance()
    RoomState.reset_instance()
    SeatManager.reset_instance()


# --- 纯函数：resolve_command_level ---


def test_resolve_reads_level_of_empty_key_for_call_without_parameters():
    command_info = {"prefix": "playlist", "level": 2, "subcommands": {"": {"level": 1}}}

    assert resolve_command_level(command_info, []) == 1


def test_resolve_matches_named_subcommand_ignoring_case():
    command_info = {
        "prefix": "timer",
        "level": 2,
        "subcommands": {"": {"level": 1}, "list": {"level": 3}},
    }

    assert resolve_command_level(command_info, ["LIST"]) == 3
    assert resolve_command_level(command_info, ["list"]) == 3


def test_resolve_matches_configured_subcommand_key_ignoring_case():
    command_info = {
        "prefix": "timer",
        "level": 2,
        "subcommands": {"": {"level": 1}, "List": {"level": 3}},
    }

    assert resolve_command_level(command_info, ["list"]) == 3


def test_resolve_falls_back_to_wildcard_for_unmatched_parameters():
    command_info = {
        "prefix": "timer",
        "level": 2,
        "subcommands": {"": {"level": 1}, "*": {"level": 5}},
    }

    assert resolve_command_level(command_info, ["whatever"]) == 5


def test_resolve_falls_back_to_top_level_when_no_subcommands_configured():
    assert resolve_command_level({"prefix": "play", "level": 3}, ["晴天"]) == 3


def test_resolve_falls_back_to_top_level_when_empty_key_is_absent():
    command_info = {"prefix": "timer", "level": 2, "subcommands": {"*": {"level": 5}}}

    assert resolve_command_level(command_info, []) == 2


def test_resolve_falls_back_to_top_level_when_wildcard_is_absent():
    command_info = {"prefix": "timer", "level": 2, "subcommands": {"list": {"level": 3}}}

    assert resolve_command_level(command_info, ["del"]) == 2


def test_resolve_defaults_to_level_one_when_nothing_is_configured():
    assert resolve_command_level({"prefix": "play"}, []) == 1


def test_resolve_accepts_scalar_shorthand():
    command_info = {"prefix": "timer", "level": 2, "subcommands": {"": 1, "*": 5}}

    assert resolve_command_level(command_info, []) == 1
    assert resolve_command_level(command_info, ["del"]) == 5


# --- 集成：CommandManager 使用解析结果做门禁 ---


def _playlist_command_info():
    return {
        "prefix": "playlist",
        "level": 2,
        "subcommands": {"": {"level": 1}, "*": {"level": 2}},
        "parameters": [],
        "error_template": "Failed to play playlist, because {error}",
        "response_template": "{message}",
    }


async def _run(command_info, nickname, level):
    from ushareiplay.managers.command_manager import CommandManager

    cm = (
        CommandManager.instance()
        if CommandManager.is_initialized()
        else CommandManager.initialize()
    )
    cm.configure_runtime(RuntimeStub())
    cm._handler = HandlerStub(config={"system_users": ["Timer"]})

    dummy_cmd = DummyCommand()
    msg = MessageInfoStub(nickname=nickname, content=f":{command_info['prefix']}")
    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = SimpleNamespace(level=level)
        res = await cm.process_command(dummy_cmd, msg, command_info)
    return dummy_cmd, res


@pytest.mark.asyncio
async def test_process_command_allows_bare_call_for_low_level_user():
    command_info = _playlist_command_info()
    command_info["parameters"] = []

    dummy_cmd, res = await _run(command_info, "Alice", 1)

    assert dummy_cmd.called is True
    assert "OK" in res


@pytest.mark.asyncio
async def test_process_command_blocks_parameterised_call_for_low_level_user():
    command_info = _playlist_command_info()
    command_info["parameters"] = ["欧美流行"]

    dummy_cmd, res = await _run(command_info, "Alice", 1)

    assert dummy_cmd.called is False
    assert "需要等级 2" in res


@pytest.mark.asyncio
async def test_process_command_allows_parameterised_call_for_high_level_user():
    command_info = _playlist_command_info()
    command_info["parameters"] = ["欧美流行"]

    dummy_cmd, res = await _run(command_info, "Alice", 2)

    assert dummy_cmd.called is True
    assert "OK" in res
