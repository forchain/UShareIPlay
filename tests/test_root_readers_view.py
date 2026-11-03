"""根级配置读取走类型化视图：命令目录、睡眠、记忆、角色。

这些读者以前各自猜「手上这份映射是根配置还是应用段」。现在它们只吃
`ConfigView`，读到的内容必须与同一份配置的裸字典形态完全一致。
"""

import datetime as dt

import pytest

from ushareiplay.core.command_catalogue import CommandCatalogue
from ushareiplay.core.config_view import ConfigView
from ushareiplay.core.roles import RolePolicy
from ushareiplay.managers.memory_manager import MemoryManager
from ushareiplay.managers.sleep_manager import SleepManager


@pytest.fixture
def sleep_manager():
    """真的 SleepManager 单例：构造完就复位，别把实例留给别的用例。"""

    def build(config):
        SleepManager.reset_instance()
        return SleepManager.initialize(ConfigView(config))

    yield build
    SleepManager.reset_instance()


def test_command_catalogue_from_the_view_matches_the_plain_dict_catalogue():
    raw = {
        "commands": [
            {"prefix": "play", "level": 2, "description": "播放"},
            {"prefix": "seat", "level": 1, "description": "座位"},
        ],
        "sleep": {"blocked_commands": ["play"]},
    }

    from_view = CommandCatalogue.from_config(ConfigView(raw))
    from_dict = CommandCatalogue.from_config(raw)

    assert [d.prefix for d in from_view.definitions] == [
        d.prefix for d in from_dict.definitions
    ]
    assert [d.level for d in from_view.definitions] == [
        d.level for d in from_dict.definitions
    ]
    assert [d.description for d in from_view.definitions] == [
        d.description for d in from_dict.definitions
    ]


def test_command_catalogue_from_the_view_reads_the_sleep_blocked_commands():
    raw = {
        "commands": [{"prefix": "play", "level": 1}],
        "sleep": {"blocked_commands": ["play"]},
    }

    from_view = CommandCatalogue.from_config(ConfigView(raw))
    from_dict = CommandCatalogue.from_config(raw)

    assert from_view.is_sleep_blocked("play") is from_dict.is_sleep_blocked("play")
    assert from_view.is_sleep_blocked("seat") is from_dict.is_sleep_blocked("seat")


def test_sleep_manager_reads_the_window_and_the_enabled_flag_from_the_view(sleep_manager):
    manager = sleep_manager(
        {
            "sleep": {
                "enabled": True,
                "start": "23:00",
                "end": "06:00",
            }
        }
    )

    assert manager.get_default_enabled() is True
    assert manager.get_window_start_str() == "23:00"
    assert manager.get_window_end_str() == "06:00"
    assert manager.is_in_sleep_window(dt.time(23, 30)) is True
    assert manager.is_in_sleep_window(dt.time(12, 0)) is False


def test_sleep_manager_reads_the_blocked_commands_from_the_view(sleep_manager):
    manager = sleep_manager(
        {
            "commands": [{"prefix": "play", "level": 1}],
            "sleep": {
                "enabled": True,
                "start": "00:00",
                "end": "00:00",
                "blocked_commands": ["play"],
            },
        }
    )

    assert manager.is_blocked_command("play", dt.time(12, 0)) is True
    assert manager.is_blocked_command("seat", dt.time(12, 0)) is False


def test_memory_manager_reads_the_llm_memory_section_from_the_view():
    MemoryManager.reset_instance()
    manager = MemoryManager.initialize()
    try:
        manager.configure(
            ConfigView(
                {
                    "llm": {
                        "memory": {
                            "enabled": False,
                            "min_messages": 3,
                            "min_level_for_long_term": 42,
                            "timeout": 12.5,
                        }
                    }
                }
            )
        )

        assert manager.is_enabled is False
        assert manager.min_messages == 3
        assert manager.min_level_for_long_term == 42
        assert manager.timeout == 12.5
    finally:
        MemoryManager.reset_instance()


def test_role_policy_resolves_the_roles_from_the_view():
    policy = RolePolicy(
        ConfigView(
            {
                "soul": {
                    "room_owner": "Alice",
                    "admin_users": ["Bob"],
                    "system_users": ["Cron"],
                }
            }
        )
    )

    assert policy.room_owner == "Alice"
    assert policy.configured_room_owner == "Alice"
    assert policy.is_room_owner("Alice") is True
    assert policy.is_admin("Bob") is True
    assert policy.is_admin("Alice") is True
    assert policy.is_admin("Outlier") is False
    assert policy.is_system_user("Cron") is True
    assert policy.is_system_user("Timer") is False
