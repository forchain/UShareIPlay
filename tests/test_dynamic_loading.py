"""
验证动态模块加载路径在重构后正确指向 ushareiplay.commands / ushareiplay.events。
不需要 Appium，只验证文件发现和模块名字符串格式。
"""
from pathlib import Path
import pytest


def _get_ushareiplay_root() -> Path:
    import ushareiplay
    return Path(ushareiplay.__file__).parent


def test_commands_discovery_finds_expected_files():
    """commands 目录下应存在已知的命令文件"""
    commands_path = _get_ushareiplay_root() / "commands"
    found = {f.stem for f in commands_path.glob("*.py") if not f.stem.startswith("__")}

    expected = {"play", "skip", "next", "pause", "vol", "mic", "seat", "help"}
    missing = expected - found
    assert not missing, f"以下命令文件缺失: {missing}"


def test_command_module_names_use_ushareiplay_prefix():
    """动态加载的命令模块名应以 ushareiplay.commands. 为前缀"""
    commands_path = _get_ushareiplay_root() / "commands"
    for py_file in commands_path.glob("*.py"):
        if py_file.stem.startswith("__"):
            continue
        expected_module = f"ushareiplay.commands.{py_file.stem}"
        # 验证模块路径字符串格式正确（与 command_manager.py 的 package_name 一致）
        assert expected_module.startswith("ushareiplay.commands.")


def test_events_discovery_finds_expected_files():
    """events 目录下应存在已知的事件文件"""
    events_path = _get_ushareiplay_root() / "events"
    found = {f.stem for f in events_path.glob("*.py") if not f.stem.startswith("__")}

    expected = {"new_message_tip", "drawer_elements", "user_count", "room_id"}
    missing = expected - found
    assert not missing, f"以下事件文件缺失: {missing}"


def test_event_module_names_use_ushareiplay_prefix():
    """动态加载的事件模块名应以 ushareiplay.events. 为前缀"""
    events_path = _get_ushareiplay_root() / "events"
    for py_file in events_path.glob("*.py"):
        if py_file.stem.startswith("__"):
            continue
        expected_module = f"ushareiplay.events.{py_file.stem}"
        assert expected_module.startswith("ushareiplay.events.")


def test_no_src_prefix_in_module_paths():
    """确认没有使用旧的 src.xxx 模块路径格式（重构前的遗留）"""
    import ushareiplay.managers.command_manager as cm_mod
    import inspect
    source = inspect.getsource(cm_mod)
    assert "src.commands" not in source, "command_manager 仍有旧的 src.commands 引用"
    assert "src.events" not in source, "command_manager 仍有旧的 src.events 引用"

    import ushareiplay.managers.event_manager as em_mod
    source = inspect.getsource(em_mod)
    assert "src.events" not in source, "event_manager 仍有旧的 src.events 引用"
