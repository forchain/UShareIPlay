"""配置热重载（#469）：元素绑定重绑 + 热重载编排。

两个公开缝：
- `EventManager.rebind_elements()` —— 运行时按当前配置重建元素 key → 事件模块映射；
- `ConfigReloadManager.reload()` —— 读盘、校验、原地生效、回报差异。

全程用假 handler / 假配置，不碰设备、不碰网络。
"""

from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
import yaml

import ushareiplay.events as events_package
from ushareiplay.core.roles import RolePolicy
from ushareiplay.core.runtime_services import RuntimeInputPipeline
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


def _soul_config(risk_elements):
    return {
        "room_owner": "Joyer",
        "admin_users": ["Outlier"],
        "risk_elements": list(risk_elements),
        "elements": {
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


def _make_controller(soul_config):
    """组合根的最小替身：根配置 + 两个 handler + 事件管理器。"""
    root = {
        "soul": soul_config,
        "qq_music": {"elements": {"play_button": "id/play"}},
        "device": {"name": "emulator"},
    }
    event_manager = _make_event_manager(soul_config)
    event_manager.load_event_module("risk_elements")
    controller = SimpleNamespace(
        config=root,
        soul_handler=SimpleNamespace(config=soul_config),
        music_handler=SimpleNamespace(config=root["qq_music"]),
        event_manager=event_manager,
    )
    return controller, event_manager


def _write_config(path, soul_config):
    path.write_text(
        yaml.safe_dump({"soul": soul_config}, allow_unicode=True), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# EventManager：运行时重绑
# --------------------------------------------------------------------------


def test_rebind_elements_rebuilds_the_mapping_from_the_current_config():
    soul = _soul_config(["collapse_seats"])
    _controller, event_manager = _make_controller(soul)

    assert event_manager.element_to_event == {"collapse_seats": "risk_elements"}

    soul["risk_elements"] = ["input_drawer"]
    mapping = event_manager.rebind_elements()

    assert mapping == {"input_drawer": "risk_elements"}
    assert event_manager.element_to_event == {"input_drawer": "risk_elements"}


def test_rebind_elements_keeps_the_element_to_event_object_identity():
    _controller, event_manager = _make_controller(_soul_config(["collapse_seats"]))
    mapping_before = event_manager.element_to_event

    event_manager.rebind_elements()

    assert event_manager.element_to_event is mapping_before


# --------------------------------------------------------------------------
# ConfigReloadManager：热重载编排
# --------------------------------------------------------------------------


def test_reload_applies_the_new_config_in_place_and_reports_the_mapping_diff(tmp_path):
    controller, event_manager = _make_controller(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]))

    report = ConfigReloadManager(controller, config_path=str(config_path)).reload()

    assert report.success is True
    # 活对象身份不变：换了对象，缓存了旧 dict 的组件就会继续用旧选择器
    assert controller.config["soul"] is controller.soul_handler.config
    assert controller.config["qq_music"] is controller.music_handler.config
    assert controller.soul_handler.config["risk_elements"] == ["input_drawer"]
    assert event_manager.element_to_event == {"input_drawer": "risk_elements"}
    assert report.diff.added == {"input_drawer": "risk_elements"}
    assert report.diff.removed == {"collapse_seats": "risk_elements"}
    assert report.diff.remapped == {}


def test_reload_reports_the_removed_and_remapped_element_bindings(tmp_path):
    controller, event_manager = _make_controller(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]))

    report = ConfigReloadManager(controller, config_path=str(config_path)).reload()

    rendered = report.render()
    assert "配置热重载成功" in rendered
    assert "collapse_seats" in rendered
    assert "input_drawer" in rendered


def test_reload_keeps_the_live_config_when_the_file_is_broken(tmp_path):
    controller, event_manager = _make_controller(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    config_path.write_text("soul: [unclosed\n", encoding="utf-8")

    report = ConfigReloadManager(controller, config_path=str(config_path)).reload()

    assert report.success is False
    assert controller.soul_handler.config["risk_elements"] == ["collapse_seats"]
    assert (
        controller.soul_handler.config["elements"]["collapse_seats"]
        == "cn.soulapp.android:id/collapseSeats"
    )
    assert event_manager.element_to_event == {"collapse_seats": "risk_elements"}
    assert "配置热重载失败" in report.render()


def test_reload_keeps_the_live_config_when_soul_elements_is_missing(tmp_path):
    controller, event_manager = _make_controller(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"risk_elements": ["input_drawer"]})

    report = ConfigReloadManager(controller, config_path=str(config_path)).reload()

    assert report.success is False
    assert controller.soul_handler.config["risk_elements"] == ["collapse_seats"]
    assert event_manager.element_to_event == {"collapse_seats": "risk_elements"}


def test_reload_keeps_the_live_config_when_the_root_is_not_a_mapping(tmp_path):
    controller, _event_manager = _make_controller(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    report = ConfigReloadManager(controller, config_path=str(config_path)).reload()

    assert report.success is False
    assert controller.soul_handler.config["risk_elements"] == ["collapse_seats"]


# --------------------------------------------------------------------------
# 控制台 `!reload` 与热重载串起来
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_console_reload_echoes_the_element_binding_diff(tmp_path):
    controller, event_manager = _make_controller(_soul_config(["collapse_seats"]))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, _soul_config(["input_drawer"]))

    logger = _Logger()
    screen = []
    pipeline = RuntimeInputPipeline(
        input_queue=Queue(),
        room_owner_provider=lambda: "Joyer",
        logger=logger,
        send_screen_message=screen.append,
        reload_config=lambda: ConfigReloadManager(
            controller, config_path=str(config_path)
        ).reload().render(),
        is_admin=RolePolicy(controller.config).is_admin,
    )
    pipeline.input_queue.put(("!reload", "console"))
    await pipeline.drain()

    echo = "\n".join(logger.critical_messages)
    assert "配置热重载成功" in echo
    assert "collapse_seats" in echo
    assert "input_drawer" in echo
    assert event_manager.element_to_event == {"input_drawer": "risk_elements"}
    assert screen == []
