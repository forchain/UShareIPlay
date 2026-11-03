"""缺必需的选择器就当场失败（ADR-0012 的 fail-fast 启动校验）。

机器人启动前就知道「哪个选择器缺了」，而不是等到运行期操作 UI 时才炸：
- 组合根 `AppController` 构造时就校验必需选择器；
- `config.local.yaml` 想覆盖元素定义，当场拒绝（元素选择器的唯一事实源
  是 `config.yaml`，见 AGENTS.md）。
"""

import asyncio
from pathlib import Path

import pytest
import yaml

import ushareiplay.__main__ as app_main
from ushareiplay.core.app_controller import AppController
from ushareiplay.core.config_loader import ConfigLoader
from ushareiplay.core.config_view import (
    ConfigView,
    MissingConfigSection,
    MissingElementKey,
    REQUIRED_ELEMENTS,
)


def _complete_config():
    """一份通过启动校验的配置：两个段与全部必需选择器都在。

    必需清单直接取自 `REQUIRED_ELEMENTS`：清单增项时这份配置自动跟上，
    测试不会因为清单变了而假装「配置是全的」。
    """
    return {
        section_name: {
            "elements": {key: f"cn.example:id/{key}" for key in keys}
        }
        for section_name, keys in REQUIRED_ELEMENTS.items()
    }


def _config_without(section_name, element_key):
    config = _complete_config()
    config[section_name]["elements"].pop(element_key)
    return config


def test_complete_config_passes_the_startup_validation():
    ConfigView(_complete_config()).validate_required_elements()


def test_shipped_config_yaml_passes_the_startup_validation():
    """仓库里真正提交的 config.yaml 必须能过启动校验（清单与文件不能各说各话）。"""
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    ConfigView(config).validate_required_elements()


def test_config_errors_stop_the_restart_loop(monkeypatch):
    """配置错误重试也不会好：不打十遍崩溃日志，直接以非零码退出。"""

    async def _failing_run_app():
        raise MissingElementKey("soul", "button_send")

    monkeypatch.setattr(app_main, "run_app", _failing_run_app)

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(app_main.main())

    assert excinfo.value.code == 2


def test_missing_soul_element_key_fails_the_startup_validation():
    view = ConfigView(_config_without("soul", "input_box"))

    with pytest.raises(MissingElementKey) as excinfo:
        view.validate_required_elements()

    assert excinfo.value.section == "soul"
    assert excinfo.value.key == "input_box"


def test_missing_qq_music_element_key_fails_the_startup_validation():
    view = ConfigView(_config_without("qq_music", "search_entry"))

    with pytest.raises(MissingElementKey) as excinfo:
        view.validate_required_elements()

    assert excinfo.value.section == "qq_music"
    assert excinfo.value.key == "search_entry"


def test_missing_section_fails_the_startup_validation():
    config = _complete_config()
    config.pop("qq_music")
    view = ConfigView(config)

    with pytest.raises(MissingConfigSection) as excinfo:
        view.validate_required_elements()

    assert excinfo.value.section == "qq_music"


def test_every_required_element_is_actually_checked():
    """校验清单与 REQUIRED_ELEMENTS 一一对应：清单里的每一项都必须会被拦下。"""
    for section_name, keys in REQUIRED_ELEMENTS.items():
        for key in keys:
            view = ConfigView(_config_without(section_name, key))
            with pytest.raises(MissingElementKey):
                view.validate_required_elements()


def test_composition_root_fails_loudly_on_a_missing_element():
    """组合根构造时就失败：缺选择器的机器人根本起不来。"""
    config = _config_without("soul", "button_send")

    try:
        with pytest.raises(MissingElementKey) as excinfo:
            AppController.initialize(config)

        assert excinfo.value.section == "soul"
        assert excinfo.value.key == "button_send"
    finally:
        AppController.reset_instance()


def _write_configs(tmp_path, base, local):
    config_path = tmp_path / "config.yaml"
    local_path = tmp_path / "config.local.yaml"
    config_path.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    local_path.write_text(yaml.safe_dump(local, allow_unicode=True), encoding="utf-8")
    return config_path


def test_local_config_can_override_the_soul_elements(tmp_path, caplog):
    config_path = _write_configs(
        tmp_path,
        {"soul": {"elements": {"user_count": "tv1"}}},
        {"soul": {"elements": {"user_count": "tv2"}}},
    )

    with caplog.at_level("WARNING"):
        loaded = ConfigLoader.load_config(config_path)

    assert loaded["soul"]["elements"]["user_count"] == "tv2"
    assert "soul.elements" in caplog.text


def test_local_config_can_override_the_root_elements(tmp_path, caplog):
    config_path = _write_configs(
        tmp_path,
        {"soul": {"elements": {"user_count": "tv1"}}},
        {"elements": {"user_count": "tv2"}},
    )

    with caplog.at_level("WARNING"):
        loaded = ConfigLoader.load_config(config_path)

    assert loaded["elements"]["user_count"] == "tv2"
    assert "elements" in caplog.text


def test_local_config_can_override_the_soul_risk_elements(tmp_path, caplog):
    config_path = _write_configs(
        tmp_path,
        {"soul": {"risk_elements": ["collapse_seats"]}},
        {"soul": {"risk_elements": ["close_widget"]}},
    )

    with caplog.at_level("WARNING"):
        loaded = ConfigLoader.load_config(config_path)

    assert loaded["soul"]["risk_elements"] == ["close_widget"]
    assert "soul.risk_elements" in caplog.text


def test_local_config_without_element_override_is_still_merged(tmp_path):
    """只有元素定义被拒绝：普通参数照常覆盖。"""
    config_path = _write_configs(
        tmp_path,
        {"soul": {"elements": {"user_count": "tv1"}, "room_owner": "Joyer"}},
        {"soul": {"room_owner": "Alice"}},
    )

    loaded = ConfigLoader.load_config(config_path)

    assert loaded["soul"]["room_owner"] == "Alice"
    assert loaded["soul"]["elements"]["user_count"] == "tv1"
