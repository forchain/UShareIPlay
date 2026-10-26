"""子命令级权限等级（issue #465）与 :playlist 的分级门禁（issue #466）。

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

文件分三段：
1. 纯函数单元测试（`resolve_command_level` / `min_command_level`）；
2. CommandManager 门禁（拿解析结果卡用户等级）；
3. config.yaml 驱动的端到端（真实命令原文 + 真实配置）。
"""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from ushareiplay.core.chat_intake import normalize_command_text
from ushareiplay.core.command_parser import CommandParser
from ushareiplay.core.roles import min_command_level, resolve_command_level

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


def test_resolve_ignores_string_scalar_as_level():
    """字符串标量不是等级写法（只认字典与整数标量），按「没写等级」处理。"""
    command_info = {"prefix": "timer", "level": 2, "subcommands": {"": "1"}}

    assert resolve_command_level(command_info, []) == 2


def test_resolve_named_subcommand_without_level_falls_back_to_wildcard():
    """具名子命令没写等级时，先看 `'*'` 规则，而不是直接回顶层。"""
    command_info = {
        "prefix": "timer",
        "level": 2,
        "subcommands": {"": {"level": 1}, "list": {"description": "列出定时器"}, "*": {"level": 5}},
    }

    assert resolve_command_level(command_info, ["list"]) == 5


def test_resolve_named_subcommand_without_level_falls_back_to_top_level():
    """`'*'` 规则也没写等级时，才回顶层等级。"""
    command_info = {
        "prefix": "timer",
        "level": 2,
        "subcommands": {"": {"level": 1}, "list": {"description": "列出定时器"}},
    }

    assert resolve_command_level(command_info, ["list"]) == 2


def test_resolve_no_arg_form_without_level_ignores_wildcard():
    """无参形态没写等级时直接回顶层 —— `'*'` 只管带参调用。"""
    command_info = {
        "prefix": "timer",
        "level": 4,
        "subcommands": {"": {"description": "无参形态"}, "*": {"level": 1}},
    }

    assert resolve_command_level(command_info, []) == 4


# --- 纯函数：min_command_level ---


def test_min_command_level_returns_lowest_level_across_forms():
    command_info = {
        "prefix": "playlist",
        "level": 2,
        "subcommands": {"": {"level": 1}, "*": {"level": 2}},
    }

    assert min_command_level(command_info) == 1


def test_min_command_level_is_top_level_without_subcommands():
    assert min_command_level({"prefix": "play", "level": 3}) == 3


def test_min_command_level_defaults_to_one():
    assert min_command_level({"prefix": "play"}) == 1


def test_min_command_level_counts_subcommand_without_level_as_wildcard_level():
    command_info = {
        "prefix": "timer",
        "level": 4,
        "subcommands": {"": {"level": 3}, "list": {"description": "列出定时器"}, "*": {"level": 2}},
    }

    assert min_command_level(command_info) == 2


def test_min_command_level_counts_no_arg_form_without_level_as_top_level():
    command_info = {
        "prefix": "timer",
        "level": 4,
        "subcommands": {"": {"description": "无参形态"}, "*": {"level": 2}},
    }

    assert min_command_level(command_info) == 2


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


async def _run(command_info, nickname, level, content=None):
    from ushareiplay.managers.command_manager import CommandManager

    cm = CommandManager.instance()
    cm.configure_runtime(RuntimeStub())
    cm._handler = HandlerStub(config={"system_users": ["Timer"]})

    dummy_cmd = DummyCommand()
    msg = MessageInfoStub(
        nickname=nickname,
        content=content if content is not None else f":{command_info['prefix']}",
    )
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


# --- 端到端：真实 config.yaml + 真实命令原文 ---


def _real_commands_config():
    """config.yaml 里真实的 commands 段。"""
    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    return config["commands"]


def _playlist_config():
    """config.yaml 里 :playlist 的真实配置。"""
    for cmd in _real_commands_config():
        if cmd.get("prefix") == "playlist":
            return cmd
    raise AssertionError("config.yaml 里找不到 playlist 命令")


def _parse_real(raw: str) -> dict:
    """用真实 config.yaml 把命令原文解析成 command info。"""
    parser = CommandParser(_real_commands_config())
    cmd_info = parser.parse_command(normalize_command_text(raw))
    assert cmd_info is not None, f"真实配置里解析不出命令：{raw}"
    return cmd_info


def test_real_playlist_config_declares_subcommand_levels():
    cmd = _playlist_config()

    assert cmd["level"] == 2
    assert cmd["subcommands"] == {"": {"level": 1}, "*": {"level": 2}}
    assert resolve_command_level(cmd, []) == 1
    assert resolve_command_level(cmd, ["欧美流行"]) == 2


def test_real_playlist_command_string_is_parsed_into_parameters():
    cmd_info = _parse_real(":playlist 欧美流行")

    assert cmd_info["prefix"] == "playlist"
    assert cmd_info["parameters"] == ["欧美流行"]


@pytest.mark.asyncio
async def test_playlist_bare_call_is_allowed_for_level_one_user():
    cmd_info = _parse_real(":playlist")

    dummy_cmd, res = await _run(cmd_info, "Alice", 1, content=":playlist")

    assert dummy_cmd.called is True
    assert "OK" in res


@pytest.mark.asyncio
async def test_playlist_with_argument_is_blocked_for_level_one_user():
    cmd_info = _parse_real(":playlist 欧美流行")

    dummy_cmd, res = await _run(cmd_info, "Alice", 1, content=":playlist 欧美流行")

    assert dummy_cmd.called is False
    assert "需要等级 2" in res


@pytest.mark.asyncio
async def test_playlist_is_allowed_for_level_two_user():
    bare_cmd, bare_res = await _run(_parse_real(":playlist"), "Alice", 2, content=":playlist")
    arg_cmd, arg_res = await _run(
        _parse_real(":playlist 欧美流行"), "Alice", 2, content=":playlist 欧美流行"
    )

    assert bare_cmd.called is True
    assert "OK" in bare_res
    assert arg_cmd.called is True
    assert "OK" in arg_res
