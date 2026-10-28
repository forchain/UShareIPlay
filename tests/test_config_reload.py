"""配置热重载（#469）：元素绑定重绑 + 热重载编排。

三个公开缝：
- `EventManager.rebind_elements()` —— 运行时按当前配置重建元素 key → 事件模块映射；
- `ConfigReloadManager.reload()` —— 读盘、校验、原地生效、回报差异；
- `RuntimeInputPipeline.drain()` —— 控制台 `!reload` 入口。

全程用假 handler / 假配置，不碰设备、不碰网络。
"""

import inspect
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
import yaml

import ushareiplay.events as events_package
from ushareiplay.core.app_controller import AppController
from ushareiplay.core.roles import RolePolicy
from ushareiplay.core.runtime_services import RuntimeInputPipeline
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.config_reload_manager import ConfigReloadManager
from ushareiplay.managers.event_manager import EventManager


class _Logger:
    def __init__(self):
        self.critical_messages = []

    def critical(self, message):
        self.critical_messages.append(message)

    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def _soul_config(risk_elements, elements=None):
    return {
        "room_owner": "Joyer",
        "admin_users": ["Outlier"],
        "risk_elements": list(risk_elements),
        "elements": elements if elements is not None else {
            "collapse_seats": "cn.soulapp.android:id/collapseSeats",
            "input_drawer": "cn.soulapp.android:id/inputDrawer",
        },
    }


def _make_event_manager(soul_config):
    manager = EventManager.__new__(EventManager)
    manager._handler = SimpleNamespace(
        logger=_Logger(),
        config=soul_config,
        controller=SimpleNamespace(config={"soul": soul_config}),
    )
    manager._logger = manager._handler.logger
    manager._config = manager._handler.config
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    manager.events_path = Path(events_package.__file__).parent
    manager.event_modules = {}
    manager.element_to_event = {}
    manager._initialized = False
    manager._consecutive_unknown_pages = 0
    return manager


def _make_runtime(soul_config):
    """组合根的最小替身：根配置 + 两个活配置段 + 事件管理器 + 命令管理器。"""
    root = {
        "soul": soul_config,
        "qq_music": {"elements": {"play_button": "id/play"}},
        "commands": [{"prefix": "play", "level": 1}],
        "device": {"name": "emulator"},
    }
    event_manager = _make_event_manager(soul_config)
    event_manager.load_event_module("risk_elements")
    return root, event_manager


def _make_reload_manager(root, event_manager, command_manager, config_path):
    """依赖显式注入（ADR-0009 §1）：热重载器自己不回头去翻控制器。"""
    return ConfigReloadManager(
        root_config=root,
        soul_config=root["soul"],
        qq_music_config=root["qq_music"],
        event_manager=event_manager,
        command_manager=command_manager,
        config_path=str(config_path),
    )


def _write_config(path, soul_config, qq_music_config=None, commands=None, omit=()):
    """写一份配置文件。

    默认写全机器人启动需要的东西（soul / qq_music / commands），这样每个用例
    只关心自己那一个变量；omit 里的顶层键不写，用来模拟「配置缺了一块」。
    """
    payload = {"soul": soul_config}
    if "qq_music" not in omit:
        payload["qq_music"] = (
            qq_music_config
            if qq_music_config is not None
            else {"elements": {"play_button": "id/play"}}
        )
    if "commands" not in omit:
        payload["commands"] = (
            commands if commands is not None else [{"prefix": "play", "level": 1}]
        )
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8"
    )


@pytest.fixture
def command_manager():
    """真的 CommandManager：命令解析器重绑的效果要能被 parse_command 看见。"""
    CommandManager.reset_instance()
    manager = CommandManager.initialize(SimpleNamespace(logger=_Logger()))
    yield manager
    CommandManager.reset_instance()


# --------------------------------------------------------------------------
# EventManager：运行时重绑
# --------------------------------------------------------------------------


def test_rebind_elements_rebuilds_the_mapping_from_the_current_config():
    soul = _soul_config(["collapse_seats"])
    _root, event_manager = _make_runtime(soul)

    assert event_manager.element_to_event == {"collapse_seats": "risk_elements"}

    soul["risk_elements"] = ["input_drawer"]
    mapping = event_manager.rebind_elements()

    assert mapping == {"input_drawer": "risk_elements"}
    assert event_manager.element_to_event == {"input_drawer": "risk_elements"}


def test_rebind_elements_keeps_the_element_to_event_object_identity():
    _root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    mapping_before = event_manager.element_to_event

    event_manager.rebind_elements()

    assert event_manager.element_to_event is mapping_before


# --------------------------------------------------------------------------
# ConfigReloadManager：依赖注入契约
# --------------------------------------------------------------------------


def test_config_reload_manager_takes_its_dependencies_explicitly():
    """ADR-0009 §1：依赖在 __init__ 里显式注入，不在调用时回头翻控制器。"""
    parameters = inspect.signature(ConfigReloadManager.__init__).parameters

    assert "controller" not in parameters
    assert {
        "root_config",
        "soul_config",
        "qq_music_config",
        "event_manager",
        "command_manager",
        "config_path",
    } <= set(parameters)


def _make_controller_with_live_sections():
    """最小控制器替身：两个 handler 手里就是根配置里那两个段。"""
    controller = AppController.__new__(AppController)
    controller.config = {
        "soul": {"elements": {"collapse_seats": "id/collapse"}},
        "qq_music": {"elements": {"play_button": "id/play"}},
        "commands": [{"prefix": "play", "level": 1}],
    }
    controller.soul_handler = SimpleNamespace(config=controller.config["soul"])
    controller.music_handler = SimpleNamespace(config=controller.config["qq_music"])
    controller.event_manager = SimpleNamespace(element_to_event={})
    controller.command_manager = SimpleNamespace()
    return controller


def test_composition_root_wires_the_live_config_objects():
    """热重载写的是各组件手里那个活的 dict —— 组合根接线错了就是静默空转。"""
    controller = _make_controller_with_live_sections()

    manager = controller._build_config_reload_manager()

    assert manager.root_config is controller.config
    assert manager.soul_config is controller.soul_handler.config
    assert manager.qq_music_config is controller.music_handler.config


def test_composition_root_refuses_a_copied_section():
    """接成副本的话，重载会写进副本，机器人照旧用旧选择器，控制台还报成功。"""
    controller = _make_controller_with_live_sections()
    controller.soul_handler = SimpleNamespace(config=dict(controller.config["soul"]))

    with pytest.raises(AssertionError):
        controller._build_config_reload_manager()


# --------------------------------------------------------------------------
# ConfigReloadManager：热重载编排
# --------------------------------------------------------------------------


def test_reload_applies_the_new_config_in_place_and_reports_the_mapping_diff(
    tmp_path, command_manager
):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    soul_config = root["soul"]
    qq_music_config = root["qq_music"]
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]))

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    assert report.success is True
    # 活对象身份不变：换了对象，缓存了旧 dict 的组件就会继续用旧选择器
    assert root["soul"] is soul_config
    assert root["qq_music"] is qq_music_config
    assert soul_config["risk_elements"] == ["input_drawer"]
    assert event_manager.element_to_event == {"input_drawer": "risk_elements"}
    assert report.diff.added == {"input_drawer": "risk_elements"}
    assert report.diff.removed == {"collapse_seats": "risk_elements"}
    assert report.diff.remapped == {}


def test_reload_reports_the_removed_and_remapped_element_bindings(
    tmp_path, command_manager
):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]))

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    rendered = report.render()
    assert "配置热重载成功" in rendered
    assert "collapse_seats" in rendered
    assert "input_drawer" in rendered


def test_reload_keeps_the_live_section_objects_in_the_root_config(
    tmp_path, command_manager
):
    """根配置是一次性更新的：root["soul"] 始终是各组件手里那个活对象。"""
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    soul_config = root["soul"]
    qq_music_config = root["qq_music"]
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]))

    _make_reload_manager(root, event_manager, command_manager, config_path).reload()

    assert root["soul"] is soul_config
    assert root["qq_music"] is qq_music_config
    # 事件管理器读的就是这个活对象：热重载原地换内容，它立刻看见
    assert event_manager.handler.config is soul_config
    assert soul_config["risk_elements"] == ["input_drawer"]


def test_reload_keeps_the_live_config_when_the_file_is_broken(tmp_path, command_manager):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    config_path.write_text("soul: [unclosed\n", encoding="utf-8")

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    assert report.success is False
    assert root["soul"]["risk_elements"] == ["collapse_seats"]
    assert (
        root["soul"]["elements"]["collapse_seats"]
        == "cn.soulapp.android:id/collapseSeats"
    )
    assert event_manager.element_to_event == {"collapse_seats": "risk_elements"}
    assert "配置热重载失败" in report.render()


def test_reload_keeps_the_live_config_when_soul_elements_is_missing(
    tmp_path, command_manager
):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"risk_elements": ["input_drawer"]})

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    assert report.success is False
    assert root["soul"]["risk_elements"] == ["collapse_seats"]
    assert event_manager.element_to_event == {"collapse_seats": "risk_elements"}


def test_reload_keeps_the_live_config_when_the_root_is_not_a_mapping(
    tmp_path, command_manager
):
    root, _event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    report = _make_reload_manager(
        root, _event_manager, command_manager, config_path
    ).reload()

    assert report.success is False
    assert root["soul"]["risk_elements"] == ["collapse_seats"]


@pytest.mark.parametrize(
    "omit, expected",
    [
        (("qq_music",), "qq_music"),
        (("commands",), "commands"),
    ],
)
def test_reload_keeps_the_live_config_when_the_bot_could_not_start_from_it(
    tmp_path, command_manager, omit, expected
):
    """缺了机器人启动时必须有的东西，配置不该被接受。

    少了 qq_music 或 commands，机器人重启时会直接 KeyError 起不来；热重载却
    报「成功」的话，就把机器人推进了一个重启也救不回来的状态。
    """
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]), omit=omit)

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    assert report.success is False
    assert expected in report.message
    assert root["soul"]["risk_elements"] == ["collapse_seats"]
    assert event_manager.element_to_event == {"collapse_seats": "risk_elements"}


def test_reload_keeps_the_live_config_when_qq_music_elements_is_missing(
    tmp_path, command_manager
):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]), qq_music_config={})

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    assert report.success is False
    assert "qq_music.elements" in report.message
    assert root["soul"]["risk_elements"] == ["collapse_seats"]


# --------------------------------------------------------------------------
# 选择器变化（改 XPath 是最常见的重载理由，必须看得见）
# --------------------------------------------------------------------------


def test_reload_reports_the_changed_selectors(tmp_path, command_manager):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        _soul_config(
            ["collapse_seats"],
            elements={
                "collapse_seats": "cn.soulapp.android:id/newCollapseSeats",
                "input_drawer": "cn.soulapp.android:id/inputDrawer",
            },
        ),
        qq_music_config={"elements": {"play_button": "id/play_v2"}},
    )

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    assert report.selector_diff.remapped == {
        "soul.collapse_seats": (
            "cn.soulapp.android:id/collapseSeats",
            "cn.soulapp.android:id/newCollapseSeats",
        ),
        "qq_music.play_button": ("id/play", "id/play_v2"),
    }


def test_reload_reports_the_added_and_removed_selectors(tmp_path, command_manager):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        _soul_config(
            ["collapse_seats"],
            elements={
                "collapse_seats": "cn.soulapp.android:id/collapseSeats",
                "new_key": "cn.soulapp.android:id/newKey",
            },
        ),
    )

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    assert report.selector_diff.added == {"soul.new_key": "cn.soulapp.android:id/newKey"}
    assert report.selector_diff.removed == {"soul.input_drawer": "cn.soulapp.android:id/inputDrawer"}


def test_reload_render_separates_the_binding_and_the_selector_changes(
    tmp_path, command_manager
):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        _soul_config(
            ["input_drawer"],
            elements={
                "collapse_seats": "cn.soulapp.android:id/newCollapseSeats",
                "input_drawer": "cn.soulapp.android:id/inputDrawer",
            },
        ),
    )

    rendered = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload().render()

    assert "元素绑定变化：" in rendered
    assert "选择器变化：" in rendered
    assert "soul.collapse_seats" in rendered
    assert "cn.soulapp.android:id/newCollapseSeats" in rendered


# --------------------------------------------------------------------------
# 命令定义：重载后必须重新绑定解析器
# --------------------------------------------------------------------------


def test_reload_rebinds_the_command_parser_with_the_new_commands(
    tmp_path, command_manager
):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    command_manager.initialize_parser(root["commands"])
    assert command_manager.parse_command("newcmd") is None

    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        _soul_config(["collapse_seats"]),
        commands=[{"prefix": "newcmd", "level": 3}],
    )

    _make_reload_manager(root, event_manager, command_manager, config_path).reload()

    parsed = command_manager.parse_command("newcmd")
    assert parsed is not None
    assert parsed["prefix"] == "newcmd"
    assert parsed["level"] == 3
    assert command_manager.parse_command("play") is None


def test_reload_message_states_what_was_refreshed(tmp_path, command_manager):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["collapse_seats"]))

    report = _make_reload_manager(
        root, event_manager, command_manager, config_path
    ).reload()

    assert "元素映射" in report.message
    assert "选择器" in report.message
    assert "命令定义" in report.message


# --------------------------------------------------------------------------
# 控制台 `!reload` 与热重载串起来
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_console_reload_echoes_the_element_binding_diff(tmp_path, command_manager):
    root, event_manager = _make_runtime(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]))

    logger = _Logger()
    screen = []
    pipeline = RuntimeInputPipeline(
        input_queue=Queue(),
        room_owner_provider=lambda: "Joyer",
        logger=logger,
        send_screen_message=screen.append,
        reload_config=lambda: _make_reload_manager(
            root, event_manager, command_manager, config_path
        ).reload().render(),
        is_admin=RolePolicy(root).is_admin,
    )
    pipeline.input_queue.put(("!reload", "console"))
    await pipeline.drain()

    echo = "\n".join(logger.critical_messages)
    assert "配置热重载成功" in echo
    assert "collapse_seats" in echo
    assert "input_drawer" in echo
    assert event_manager.element_to_event == {"input_drawer": "risk_elements"}
    assert screen == []
