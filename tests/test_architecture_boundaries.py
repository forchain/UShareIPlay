"""架构护栏：全仓 `src/ushareiplay` 边界、依赖方向与无单例守卫。

AST 扫描而不是文本 grep：注释与字符串里出现 "appium" 不算违规。护栏本身用
合成源码验证 —— 每加一条非法 import、`.instance()` 调用或 `Singleton` 继承都必须被抓住。
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
PKG_ROOT = SRC_ROOT / "ushareiplay"
MODULES_ROOT = PKG_ROOT / "modules"
CORE_ROOT = PKG_ROOT / "core"
BOOTSTRAP_ROOT = PKG_ROOT / "bootstrap"
INBOUND_CHAT_ROOT = PKG_ROOT / "adapters" / "inbound" / "chat"
INBOUND_RUNTIME_ROOT = PKG_ROOT / "adapters" / "inbound" / "runtime"
INBOUND_UI_EVENTS_ROOT = PKG_ROOT / "adapters" / "inbound" / "ui_events"
APPIUM_ROOT = PKG_ROOT / "adapters" / "outbound" / "appium"
PERSISTENCE_ROOT = PKG_ROOT / "adapters" / "outbound" / "persistence"
SYSTEM_ADAPTERS_ROOT = PKG_ROOT / "adapters" / "outbound" / "system"
LLM_ROOT = PKG_ROOT / "adapters" / "outbound" / "llm"

FORBIDDEN_MODULES = (
    "appium",
    "selenium",
    "tortoise",
    "openai",
    "yaml",
    "ushareiplay.adapters",
    "ushareiplay.bootstrap",
)
FORBIDDEN_IN_INBOUND_PURE = (
    "appium",
    "selenium",
    "tortoise",
    "openai",
    "yaml",
    "ushareiplay.adapters.outbound",
    "ushareiplay.bootstrap",
)
FORBIDDEN_IN_UI_EVENTS = (
    "appium",
    "selenium",
    "tortoise",
    "openai",
    "yaml",
    "ushareiplay.adapters.outbound.persistence",
    "ushareiplay.adapters.outbound.llm",
    "ushareiplay.adapters.outbound.system",
    "ushareiplay.adapters.outbound.appium.soul",
    "ushareiplay.adapters.outbound.appium.qq_music",
    "ushareiplay.bootstrap",
)
FORBIDDEN_IN_PERSISTENCE = (
    "appium",
    "selenium",
    "openai",
    "ushareiplay.adapters.inbound",
    "ushareiplay.adapters.outbound.appium",
    "ushareiplay.adapters.outbound.llm",
    "ushareiplay.adapters.outbound.system",
    "ushareiplay.bootstrap",
)
FORBIDDEN_IN_LLM = (
    "appium",
    "selenium",
    "tortoise",
    "ushareiplay.adapters.inbound",
    "ushareiplay.adapters.outbound.appium",
    "ushareiplay.adapters.outbound.persistence",
    "ushareiplay.adapters.outbound.system",
    "ushareiplay.bootstrap",
)
FORBIDDEN_IN_SYSTEM = (
    "appium",
    "selenium",
    "tortoise",
    "openai",
    "ushareiplay.adapters.inbound",
    "ushareiplay.adapters.outbound.appium",
    "ushareiplay.adapters.outbound.persistence",
    "ushareiplay.adapters.outbound.llm",
    "ushareiplay.bootstrap",
)
FORBIDDEN_IN_APPIUM = (
    "tortoise",
    "openai",
    "ushareiplay.adapters.inbound",
    "ushareiplay.adapters.outbound.persistence",
    "ushareiplay.adapters.outbound.llm",
    "ushareiplay.adapters.outbound.system",
    "ushareiplay.bootstrap",
)

_SYNTHETIC_PATH = MODULES_ROOT / "shared" / "_guard_fixture.py"
_PERSISTENCE_SYNTHETIC_PATH = PERSISTENCE_ROOT / "_guard_fixture.py"


def _package_parts(path: Path) -> list[str]:
    return list(path.resolve().relative_to(SRC_ROOT).with_suffix("").parts[:-1])


def _imported_modules(node: ast.AST, path: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []

    if node.level:
        package = _package_parts(path)
        base = package[: len(package) - (node.level - 1)]
        resolved = ".".join(base + ([node.module] if node.module else []))
    else:
        resolved = node.module or ""

    imported = [resolved] if resolved else []
    imported.extend(
        f"{resolved}.{alias.name}" if resolved else alias.name
        for alias in node.names
    )
    return imported


def _is_forbidden(module: str, forbidden_modules=FORBIDDEN_MODULES) -> bool:
    return any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for forbidden in forbidden_modules
    )


def find_violations(source: str, path: Path, forbidden_modules=FORBIDDEN_MODULES) -> list[str]:
    violations = []
    for node in ast.walk(ast.parse(source)):
        for module in _imported_modules(node, path):
            if _is_forbidden(module, forbidden_modules):
                violations.append(f"{path}:{node.lineno}: forbidden import {module}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "instance"
        ):
            violations.append(f"{path}:{node.lineno}: forbidden .instance() lookup")
        if isinstance(node, ast.Name) and node.id in ("Singleton", "SingletonMeta", "SingletonError"):
            violations.append(f"{path}:{node.lineno}: forbidden singleton symbol {node.id}")
    return violations


def _scan_root(root: Path, forbidden_modules=FORBIDDEN_MODULES) -> dict[str, list[str]]:
    files = sorted(root.rglob("*.py"))
    assert files, f"expected Python files under {root}"
    return {
        str(path): found
        for path in files
        if (found := find_violations(path.read_text(), path, forbidden_modules))
    }


def test_all_modules_packages_are_technology_and_adapter_free():
    """覆盖 modules/ 全部业务切片（shared/seat/mic/playback/room/user/command/timer）。"""
    expected_modules = {"shared", "seat", "mic", "playback", "room", "user", "command", "timer"}
    actual_modules = {p.name for p in MODULES_ROOT.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert expected_modules <= actual_modules
    assert _scan_root(MODULES_ROOT, FORBIDDEN_MODULES) == {}


def test_shared_stdlib_core_helpers_stay_technology_and_adapter_free():
    assert _scan_root(CORE_ROOT, FORBIDDEN_MODULES) == {}


def test_no_instance_lookups_or_singleton_machinery_anywhere_in_src():
    violations = []
    for path in sorted(PKG_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "instance"
            ):
                violations.append(f"{path}:{node.lineno}: .instance()")
            if isinstance(node, ast.Name) and node.id in (
                "Singleton",
                "SingletonMeta",
                "SingletonError",
            ):
                violations.append(f"{path}:{node.lineno}: {node.id}")
    assert violations == []


def test_retired_legacy_packages_and_singleton_module_are_deleted():
    for retired in (
        "commands",
        "events",
        "dal",
        "handlers",
        "managers",
        "models",
        "state",
        "helpers",
    ):
        # 只看源码文件：本地 worktree 里旧的 __pycache__ 可能还留着，它不代表模块仍在。
        stale = list((PKG_ROOT / retired).rglob("*.py"))
        assert not stale, f"retired package still has source: {retired}: {stale}"
    assert not (CORE_ROOT / "singleton.py").exists()
    assert not (CORE_ROOT / "app_controller.py").exists()


def test_inbound_chat_and_runtime_do_not_import_outbound_adapters():
    assert _scan_root(INBOUND_CHAT_ROOT, FORBIDDEN_IN_INBOUND_PURE) == {}
    assert _scan_root(INBOUND_RUNTIME_ROOT, FORBIDDEN_IN_INBOUND_PURE) == {}


def test_inbound_ui_events_do_not_import_concrete_outbound_drivers_or_persistence():
    assert _scan_root(INBOUND_UI_EVENTS_ROOT, FORBIDDEN_IN_UI_EVENTS) == {}


def test_runtime_loop_does_not_import_concrete_outbound_adapters():
    runtime_loop = BOOTSTRAP_ROOT / "runtime_loop.py"
    assert runtime_loop.exists()
    assert find_violations(
        runtime_loop.read_text(),
        runtime_loop,
        FORBIDDEN_IN_INBOUND_PURE,
    ) == []


def test_persistence_adapter_does_not_import_other_technologies_or_locate_services():
    assert _scan_root(PERSISTENCE_ROOT, FORBIDDEN_IN_PERSISTENCE) == {}


def test_llm_adapter_stays_out_of_ui_persistence_and_service_location():
    assert (LLM_ROOT / "memory_distiller.py").exists()
    assert _scan_root(LLM_ROOT, FORBIDDEN_IN_LLM) == {}


def test_system_adapters_stay_out_of_other_adapters_and_service_location():
    assert (SYSTEM_ADAPTERS_ROOT / "network_bridge.py").exists()
    assert (SYSTEM_ADAPTERS_ROOT / "log_rotation.py").exists()
    assert _scan_root(SYSTEM_ADAPTERS_ROOT, FORBIDDEN_IN_SYSTEM) == {}


def test_appium_adapters_stay_out_of_persistence_llm_and_system():
    assert _scan_root(APPIUM_ROOT, FORBIDDEN_IN_APPIUM) == {}


@pytest.mark.parametrize(
    "source",
    [
        "import tortoise\n",
        "from tortoise.models import Model\n",
    ],
)
def test_persistence_guard_allows_tortoise(source):
    assert find_violations(source, _PERSISTENCE_SYNTHETIC_PATH, FORBIDDEN_IN_PERSISTENCE) == []


@pytest.mark.parametrize(
    "source",
    [
        "import appium\n",
        "from selenium.webdriver import Chrome\n",
        "from openai import OpenAI\n",
        "from ushareiplay.adapters.outbound.appium import locator\n",
        "value = Service.instance()\n",
        "class Svc(Singleton):\n    pass\n",
    ],
)
def test_persistence_guard_rejects_a_forbidden_line(source):
    assert find_violations(source, _PERSISTENCE_SYNTHETIC_PATH, FORBIDDEN_IN_PERSISTENCE)


@pytest.mark.parametrize(
    "source",
    [
        "import appium\n",
        "import appium.webdriver\n",
        "from selenium.webdriver import Chrome\n",
        "import tortoise\n",
        "from openai import OpenAI\n",
        "from ushareiplay.adapters.outbound.system.clock import SystemClock\n",
        "from ushareiplay import adapters\n",
        "from ushareiplay.bootstrap import AppContainer\n",
        "from ...adapters.outbound.appium import locator\n",
        "value = Service.instance()\n",
        "class Svc(Singleton):\n    pass\n",
    ],
)
def test_guard_rejects_a_forbidden_line(source):
    assert find_violations(source, _SYNTHETIC_PATH)


def test_guard_allows_pure_module_code():
    source = (
        "import asyncio\n"
        "from ushareiplay.modules.shared.errors import DomainError\n"
        "from ushareiplay.modules.shared import ports\n"
        "\n"
        "def build(service):\n"
        "    return service\n"
    )

    assert find_violations(source, _SYNTHETIC_PATH) == []
