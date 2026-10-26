""":playlist 的子命令级权限（issue #466）。

裸 `:playlist` 只是读当前播放队列（只读），带歌单名会切歌（写），
所以两者用不同的等级：配置写在 config.yaml 的 commands 段里。
"""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from ushareiplay.core.command_parser import resolve_command_level

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _playlist_config():
    """config.yaml 里 :playlist 的真实配置。"""
    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    for cmd in config["commands"]:
        if cmd.get("prefix") == "playlist":
            return cmd
    raise AssertionError("config.yaml 里找不到 playlist 命令")


def _command_info(parameters):
    cmd_info = dict(_playlist_config())
    cmd_info["parameters"] = parameters
    return cmd_info


async def _run(parameters, level):
    from ushareiplay.managers.command_manager import CommandManager

    cm = (
        CommandManager.instance()
        if CommandManager.is_initialized()
        else CommandManager.initialize()
    )
    cm.configure_runtime(RuntimeStub())
    cm._handler = HandlerStub(config={"system_users": ["Timer"]})

    command_info = _command_info(parameters)
    dummy_cmd = DummyCommand()
    msg = MessageInfoStub(nickname="Alice", content=":playlist")
    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = SimpleNamespace(level=level)
        res = await cm.process_command(dummy_cmd, msg, command_info)
    return dummy_cmd, res


def test_playlist_config_declares_subcommand_levels():
    cmd = _playlist_config()

    assert resolve_command_level(cmd, []) == 1
    assert resolve_command_level(cmd, ["欧美流行"]) == 2


@pytest.mark.asyncio
async def test_playlist_bare_call_is_allowed_for_level_one_user():
    dummy_cmd, res = await _run([], 1)

    assert dummy_cmd.called is True
    assert "OK" in res


@pytest.mark.asyncio
async def test_playlist_with_argument_is_blocked_for_level_one_user():
    dummy_cmd, res = await _run(["欧美流行"], 1)

    assert dummy_cmd.called is False
    assert "需要等级 2" in res


@pytest.mark.asyncio
async def test_playlist_is_allowed_for_level_two_user():
    bare_cmd, bare_res = await _run([], 2)
    arg_cmd, arg_res = await _run(["欧美流行"], 2)

    assert bare_cmd.called is True
    assert "OK" in bare_res
    assert arg_cmd.called is True
    assert "OK" in arg_res
