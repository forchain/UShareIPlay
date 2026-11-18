"""架构护栏：`modules/` 不得依赖任何具体技术或适配器，也不得做服务定位。

AST 扫描而不是文本 grep：注释与字符串里出现 "appium" 不算违规。护栏本身用
合成源码验证 —— 每加一条非法 import 或 `.instance()` 调用都必须被抓住。
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
MODULES_ROOT = SRC_ROOT / "ushareiplay" / "modules"

FORBIDDEN_MODULES = ("appium", "selenium", "tortoise", "openai", "ushareiplay.adapters")

_SYNTHETIC_PATH = MODULES_ROOT / "shared" / "_guard_fixture.py"


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


def _is_forbidden(module: str) -> bool:
    return any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for forbidden in FORBIDDEN_MODULES
    )


def find_violations(source: str, path: Path) -> list[str]:
    violations = []
    for node in ast.walk(ast.parse(source)):
        for module in _imported_modules(node, path):
            if _is_forbidden(module):
                violations.append(f"{path}:{node.lineno}: forbidden import {module}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "instance"
        ):
            violations.append(f"{path}:{node.lineno}: forbidden .instance() lookup")
    return violations


def test_modules_do_not_import_technology_or_adapters_and_do_not_locate_services():
    module_files = sorted(MODULES_ROOT.rglob("*.py"))
    assert module_files

    violations = {
        str(path): found
        for path in module_files
        if (found := find_violations(path.read_text(), path))
    }

    assert violations == {}


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
        "from ...adapters.outbound.appium import locator\n",
        "value = Service.instance()\n",
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
