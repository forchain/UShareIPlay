"""
验证重构后 Path(__file__) 路径解析指向正确目录。
重构将模块从 src/ 移到 src/ushareiplay/，__file__ 相对层级改变，
这里确保各管理器的路径属性指向真实存在的目录。
"""
from pathlib import Path
import pytest


def test_command_manager_command_roots_exist():
    """CommandManager.command_roots 只指向入站聊天适配器目录。"""
    from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    roots = manager.command_roots
    assert len(roots) == 1
    assert roots[0].name == "chat" and roots[0].parent.name == "inbound"
    for path in roots:
        assert path.exists(), f"命令根目录不存在: {path}"
        assert path.is_dir()


def test_command_manager_command_roots_have_py_files():
    """命令根目录应包含 .py 命令文件"""
    from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    for path in manager.command_roots:
        py_files = [p for p in path.glob("*.py") if not p.stem.startswith("__")]
        assert len(py_files) > 0, f"{path} 下没有找到任何 .py 文件"


def test_event_manager_events_path_exists():
    """EventManager.events_path 应指向 src/ushareiplay/adapters/inbound/ui_events/"""
    from ushareiplay.adapters.inbound.ui_events.event_manager import EventManager
    manager = EventManager.__new__(EventManager)
    manager.__init__()
    path = manager.events_path
    assert path.exists(), f"events 目录不存在: {path}"
    assert path.is_dir()
    assert path.name == "ui_events"


def test_event_manager_events_path_has_py_files():
    """ui_events 目录应包含 .py 事件文件"""
    from ushareiplay.adapters.inbound.ui_events.event_manager import EventManager
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
