"""`:recommend` 命令层的契约（#393）。

行为测试（开关真的落到了抽屉里、回复长什么样）在
`tests/test_room_profile_recommendation.py`；这里只钉**这一层**的形状：
它必须是一个纯粹的 `BaseCommand` 子类——一个类、一个 `do_process`、没有工厂、
没有模块级 `command = None`——并且**没有**自己的 `error_message` 覆写。

`error_message` 这条是有意钉死的：`RecommendCommand` 一直沿用基类的
`'Failed to process command: {error}'`，config.yaml 的 `:recommend` 模板按这个
前缀配的。多一层覆写就等于改了用户看得见的报错，所以这里锁住。
"""

import inspect
from pathlib import Path

import pytest

from ushareiplay.commands.recommend import RecommendCommand
from ushareiplay.core.base_command import BaseCommand

COMMANDS_DIR = Path(__file__).resolve().parents[1] / "src" / "ushareiplay" / "commands"


def test_recommend_module_is_class_only():
    """一个模块一个 `BaseCommand` 子类，没有工厂、没有模块级 `command = None`。"""
    source = (COMMANDS_DIR / "recommend.py").read_text()

    assert "def create_command(" not in source
    assert "command = None" not in source


def test_recommend_declares_exactly_one_base_command_subclass():
    subclasses = [
        obj
        for obj in vars(RecommendCommand).values()
        if inspect.isclass(obj) and issubclass(obj, BaseCommand) and obj is not BaseCommand
    ]
    assert subclasses == []
    assert issubclass(RecommendCommand, BaseCommand)


def test_recommend_targets_the_soul_handler_and_keeps_the_base_error_message():
    assert RecommendCommand.handler_attr == "soul_handler"
    # 有意不覆写：沿用基类模板，用户的报错文案因此不变。
    assert "error_message" not in vars(RecommendCommand)


def test_recommend_delegates_the_toggle_instead_of_touching_the_drawer_itself():
    """命令层不得自己开窗——那是房间档案模块的事（批处理的前提）。"""
    source = inspect.getsource(RecommendCommand)

    assert "ensure_open" not in source
    assert "close_with_back" not in source
    assert "element_finder" not in source
    assert "set_recommendation" in source


@pytest.mark.asyncio
async def test_recommend_reports_the_switch_to_soul_failure_without_touching_the_manager():
    """连 Soul 都没切过去就不该去碰抽屉。"""
    handler = type(
        "_Handler",
        (),
        {"key_actions": type("_K", (), {"switch_to_app": staticmethod(lambda: False)})()},
    )()
    runtime = type("_R", (), {"soul_handler": handler, "music_handler": None})()
    cmd = RecommendCommand(runtime)

    assert await cmd.do_process(type("_M", (), {"nickname": "Console"})(), []) == {
        "error": "Failed to switch to Soul app"
    }
