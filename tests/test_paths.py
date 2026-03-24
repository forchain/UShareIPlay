"""
验证重构后 Path(__file__) 路径解析指向正确目录。
重构将模块从 src/ 移到 src/ushareiplay/，__file__ 相对层级改变，
这里确保各管理器的路径属性指向真实存在的目录。
"""
from pathlib import Path
import pytest


def test_command_manager_commands_path_exists():
    """CommandManager.commands_path 应指向 src/ushareiplay/commands/"""
    from ushareiplay.managers.command_manager import CommandManager
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    path = manager.commands_path
    assert path.exists(), f"commands 目录不存在: {path}"
    assert path.is_dir()
    assert path.name == "commands"


def test_command_manager_commands_path_has_py_files():
    """commands 目录应包含 .py 命令文件"""
    from ushareiplay.managers.command_manager import CommandManager
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    py_files = list(manager.commands_path.glob("*.py"))
    assert len(py_files) > 0, "commands 目录下没有找到任何 .py 文件"


def test_event_manager_events_path_exists():
    """EventManager.events_path 应指向 src/ushareiplay/events/"""
    from ushareiplay.managers.event_manager import EventManager
    manager = EventManager.__new__(EventManager)
    manager.__init__()
    path = manager.events_path
    assert path.exists(), f"events 目录不存在: {path}"
    assert path.is_dir()
    assert path.name == "events"


def test_event_manager_events_path_has_py_files():
    """events 目录应包含 .py 事件文件"""
    from ushareiplay.managers.event_manager import EventManager
    manager = EventManager.__new__(EventManager)
    manager.__init__()
    py_files = list(manager.events_path.glob("*.py"))
    assert len(py_files) > 0, "events 目录下没有找到任何 .py 文件"


def test_package_root_is_ushareiplay():
    """ushareiplay 包的 __file__ 应在 src/ushareiplay/ 内"""
    import ushareiplay
    pkg_path = Path(ushareiplay.__file__).parent
    assert pkg_path.name == "ushareiplay"
    assert pkg_path.parent.name == "src"
