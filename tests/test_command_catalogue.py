from pathlib import Path

import pytest

from ushareiplay.core.command_catalogue import (
    CommandCatalogue,
    CommandCatalogueError,
)
from ushareiplay.core.config_loader import ConfigLoader


def _write_command_module(directory: Path, name: str, *, base: str = "BaseCommand") -> None:
    (directory / f"{name}.py").write_text(
        "\n".join(
            [
                "from ushareiplay.core.base_command import BaseCommand",
                "",
                f"class DemoCommand({base}):",
                "    async def do_process(self, message_info, parameters):",
                "        return {}",
            ]
        ),
        encoding="utf-8",
    )


def _catalogue(tmp_path: Path, commands, **root):
    return CommandCatalogue.from_config(
        {"commands": commands, **root}, commands_path=tmp_path
    )


def test_repository_config_is_fully_backed():
    """仓库里的 config.yaml 必须与 commands/*.py 一一对应。"""
    catalogue = CommandCatalogue.from_config(ConfigLoader.load_config())

    catalogue.validate()


def test_resolve_parses_prefix_and_parameters_case_insensitively():
    catalogue = CommandCatalogue.from_config(
        {"commands": [{"prefix": "play", "level": 2}]}
    )

    invocation = catalogue.resolve(":PLAY 晴天 周杰伦")

    assert invocation is not None
    assert invocation.definition.prefix == "play"
    assert invocation.parameters == ("晴天", "周杰伦")
    assert invocation.command_info["prefix"] == "play"
    assert invocation.command_info["parameters"] == ["晴天", "周杰伦"]
    assert catalogue.resolve("players sing") is None


def test_validate_fails_when_declared_module_is_missing(tmp_path):
    catalogue = _catalogue(tmp_path, [{"prefix": "ghost", "level": 1}])

    with pytest.raises(CommandCatalogueError, match="ghost.py 不存在"):
        catalogue.validate()


def test_validate_fails_when_module_has_no_base_command(tmp_path):
    (tmp_path / "ghost.py").write_text("VALUE = 1\n", encoding="utf-8")
    catalogue = _catalogue(tmp_path, [{"prefix": "ghost", "level": 1}])

    with pytest.raises(CommandCatalogueError, match="BaseCommand 子类"):
        catalogue.validate()


def test_validate_accepts_backed_modules(tmp_path):
    _write_command_module(tmp_path, "demo")
    catalogue = _catalogue(tmp_path, [{"prefix": "demo", "level": 1}])

    catalogue.validate()


def test_validate_fails_on_duplicate_prefixes(tmp_path):
    _write_command_module(tmp_path, "demo")
    catalogue = _catalogue(
        tmp_path,
        [
            {"prefix": "demo", "level": 1},
            {"prefix": "demo", "level": 2},
        ],
    )

    with pytest.raises(CommandCatalogueError, match="重复"):
        catalogue.validate()


def test_required_level_honours_subcommands():
    catalogue = CommandCatalogue.from_config(
        {
            "commands": [
                {
                    "prefix": "level",
                    "level": 0,
                    "subcommands": {"": {"level": 0}, "*": {"level": 9}},
                }
            ]
        }
    )

    assert catalogue.required_level("level", []) == 0
    assert catalogue.required_level("level", ["张三", "3"]) == 9


def test_guest_and_sleep_policies_come_from_config():
    catalogue = CommandCatalogue.from_config(
        {
            "commands": [
                {"prefix": "play", "level": 1, "guest_allowed": True},
                {"prefix": "theme", "level": 1},
            ],
            "sleep": {"blocked_commands": ["play"]},
        }
    )

    assert catalogue.is_guest_allowed(":play") is True
    assert catalogue.is_guest_allowed("theme") is False
    assert catalogue.is_sleep_blocked("play") is True
    assert catalogue.is_sleep_blocked("theme") is False


def test_help_and_prompt_lines_are_derived_from_the_same_definitions():
    catalogue = CommandCatalogue.from_config(
        {
            "commands": [
                {"prefix": "help", "level": 0, "help": ":help 帮助", "help_order": 1},
                {"prefix": "play", "level": 2, "description": "播放", "help": ":play 歌名", "help_order": 2},
            ]
        }
    )

    assert catalogue.get_help_lines() == [
        "帮助",
        ":help 帮助",
        ":play 歌名",
    ]
    assert catalogue.get_prompt_lines() == [
        "- `:help` (所需等级: L0): help",
        "- `:play` (所需等级: L2): 播放",
    ]


def test_prompt_lines_hide_guest_blocked_commands_in_guest_room():
    catalogue = CommandCatalogue.from_config(
        {
            "commands": [
                {"prefix": "play", "level": 1, "guest_allowed": True, "description": "播放"},
                {"prefix": "theme", "level": 1, "description": "主题"},
            ]
        }
    )

    assert len(catalogue.get_prompt_lines()) == 2
    assert catalogue.get_prompt_lines(guest_room=True) == [
        "- `:play` (所需等级: L1): 播放"
    ]
