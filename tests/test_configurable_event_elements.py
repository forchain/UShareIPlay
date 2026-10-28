"""风险元素与抽屉元素的监控列表可配置，缺省时回退模块默认列表。

配置入口是 config.yaml 的 `soul.risk_elements` / `soul.drawer_elements`
（运行时由 SoulHandler.config 即 soul 段读取）。

判定规则（事件类与 EventManager 共用同一套）：
配置值只有在「非空列表且条目全部为字符串」时才算已声明；其余情况
（键缺省、null、空列表、类型错误、含非字符串条目）一律回退模块默认列表。
"""

from pathlib import Path
from types import SimpleNamespace

import yaml

from ushareiplay.events import drawer_elements as drawer_elements_module
from ushareiplay.events import risk_elements as risk_elements_module
from ushareiplay.events.drawer_elements import DrawerElementsEvent
from ushareiplay.events.risk_elements import RiskElementsEvent
from ushareiplay.managers.event_manager import EventManager

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeLogger:
    def debug(self, *_args, **_kwargs):
        return None

    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


def _handler(soul_config):
    """SoulHandler 的替身：config 即 config.yaml 的 soul 段。"""
    return SimpleNamespace(logger=_FakeLogger(), controller=None, config=soul_config)


def _event_manager(soul_config):
    manager = EventManager.__new__(EventManager)
    manager._handler = _handler(soul_config)
    manager._logger = manager._handler.logger
    manager._config = manager._handler.config
    manager._runtime = SimpleNamespace(is_ui_busy=lambda: False)
    manager.events_path = Path(risk_elements_module.__file__).parent
    manager.event_modules = {}
    manager.element_to_event = {}
    manager._initialized = True
    manager._consecutive_unknown_pages = 0
    return manager


def test_risk_elements_event_uses_the_configured_element_list():
    handler = _handler({"risk_elements": ["close_widget", "party_back"]})

    event = RiskElementsEvent(handler)

    assert event.elements == ["close_widget", "party_back"]


def test_drawer_elements_event_uses_the_configured_element_list():
    handler = _handler({"drawer_elements": ["input_drawer", "other_drawer"]})

    event = DrawerElementsEvent(handler)

    assert event.elements == ["input_drawer", "other_drawer"]


def test_risk_elements_event_falls_back_to_the_module_default_when_not_configured():
    handler = _handler({})

    event = RiskElementsEvent(handler)

    assert event.elements == risk_elements_module.__elements__
    assert "collapse_seats" in event.elements


def test_drawer_elements_event_falls_back_to_the_module_default_when_not_configured():
    handler = _handler({})

    event = DrawerElementsEvent(handler)

    assert event.elements == drawer_elements_module.__elements__
    assert "input_drawer" in event.elements


def test_risk_elements_event_falls_back_when_the_configured_list_is_empty():
    handler = _handler({"risk_elements": []})

    event = RiskElementsEvent(handler)

    assert event.elements == risk_elements_module.__elements__


def test_risk_elements_event_falls_back_when_the_configured_value_is_not_a_list():
    handler = _handler({"risk_elements": "collapse_seats"})

    event = RiskElementsEvent(handler)

    assert event.elements == risk_elements_module.__elements__


def test_risk_elements_event_falls_back_when_the_configured_list_has_non_string_entries():
    handler = _handler({"risk_elements": ["collapse_seats", 7]})

    event = RiskElementsEvent(handler)

    assert event.elements == risk_elements_module.__elements__


def test_drawer_elements_event_falls_back_when_the_configured_value_is_none():
    handler = _handler({"drawer_elements": None})

    event = DrawerElementsEvent(handler)

    assert event.elements == drawer_elements_module.__elements__


def test_risk_elements_event_reads_the_live_config_on_every_access():
    """运行时热加载改写 soul 配置后，元素列表立即生效（不做导入期快照）。"""
    handler = _handler({"risk_elements": ["close_widget"]})
    event = RiskElementsEvent(handler)

    assert event.elements == ["close_widget"]

    handler.config["risk_elements"] = ["party_back"]

    assert event.elements == ["party_back"]


def test_event_manager_registers_the_configured_risk_elements():
    manager = _event_manager({"risk_elements": ["close_widget", "party_back"]})

    module = manager.load_event_module("risk_elements")

    assert module is not None
    assert manager.element_to_event == {
        "close_widget": "risk_elements",
        "party_back": "risk_elements",
    }


def test_event_manager_registers_the_configured_drawer_elements():
    manager = _event_manager({"drawer_elements": ["other_drawer"]})

    module = manager.load_event_module("drawer_elements")

    assert module is not None
    assert manager.element_to_event == {"other_drawer": "drawer_elements"}


def test_event_manager_falls_back_to_the_module_default_elements():
    manager = _event_manager({})

    manager.load_event_module("risk_elements")

    assert manager.element_to_event == {
        key: "risk_elements" for key in risk_elements_module.__elements__
    }


def test_event_manager_falls_back_when_the_configured_list_is_empty():
    manager = _event_manager({"risk_elements": []})

    manager.load_event_module("risk_elements")

    assert manager.element_to_event == {
        key: "risk_elements" for key in risk_elements_module.__elements__
    }


def test_config_yaml_declares_the_configurable_element_lists():
    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    soul = config["soul"]

    # 漂移守卫：生效列表是 config.yaml 里的这份，模块里的 __elements__ 是代码级
    # 回退默认列表。两边一旦不一致，就说明其中一份已经过期（改了 config.yaml
    # 忘了改模块，或反过来），此时必须报错而不是让回退悄悄失效。
    assert soul["risk_elements"] == risk_elements_module.__elements__
    assert soul["drawer_elements"] == drawer_elements_module.__elements__


def test_event_manager_binding_equals_the_element_list_the_event_reports():
    """生效列表只有一处实现：EventManager 的绑定映射 = 事件实例报告的列表。"""
    manager = _event_manager({"risk_elements": ["close_widget", "party_back"]})

    module = manager.load_event_module("risk_elements")

    assert module.event.elements == ["close_widget", "party_back"]
    assert manager.element_to_event == {
        "close_widget": "risk_elements",
        "party_back": "risk_elements",
    }


def test_event_without_module_elements_binds_its_filename_derived_keys():
    """模块没有 __elements__ 时按文件名派生 key —— 列表只有一处实现，不能丢。"""
    manager = _event_manager({})

    module = manager.load_event_module("planet_tab")

    assert module.event.elements == ["planet_tab"]
    assert manager.element_to_event == {"planet_tab": "planet_tab"}
