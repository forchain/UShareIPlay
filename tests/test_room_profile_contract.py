"""收口契约：房间档案只有一个模块，且由组合根构造注入。

这是 spec #387 与 #539 的结构断言：旧管理器与过渡门面彻底消失；组合根只
构造一次房间档案；模块内部不反过来依赖上层适配器或已下线的管理器。
"""

import ast
import json
import pathlib
import subprocess
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
PKG = SRC / "ushareiplay"

# #390~#394 逐张下线、#394 收口掉最后一层门面的旧管理器模块。
RETIRED_MODULES = (
    "room_info_window",
    "topic_manager",
    "notice_manager",
    "recommendation_manager",
    "room_name_manager",
)

# ADR-0009 §2 的受保护单例清单里，这五个类必须不再出现。
RETIRED_CLASSES = (
    "RoomInfoWindow",
    "TopicManager",
    "NoticeManager",
    "RecommendationManager",
    "RoomNameManager",
)


def _python_sources(relative_to):
    return sorted(p for p in relative_to.rglob("*.py"))


def test_every_retired_manager_module_is_gone():
    assert not (PKG / "managers" / "room_info_window.py").exists()
    for module in RETIRED_MODULES:
        assert not (PKG / "managers" / f"{module}.py").exists()
    assert not (PKG / "managers" / "room_profile").exists()


def test_no_source_module_mentions_the_retired_shim():
    offenders = []
    for path in _python_sources(PKG):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "RoomInfoWindow" in line or "room_info_window" in line:
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
    assert offenders == []


@pytest.mark.parametrize("name", RETIRED_CLASSES)
def test_no_source_module_imports_a_retired_manager(name):
    offenders = []
    for path in _python_sources(PKG):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", None) or ""
                names = " ".join(alias.name for alias in node.names)
                if name in module or name in names:
                    offenders.append(f"{path.relative_to(SRC)}: {module or names}")
    assert offenders == []


def test_the_composition_root_constructs_exactly_one_room_profile():
    source = (PKG / "core" / "app_controller.py").read_text(encoding="utf-8")

    assert source.count("self.room_profile_manager = RoomProfileManager(") == 1
    assert "RoomProfileManager.initialize(" not in source
    assert "from ushareiplay.modules.room import RoomProfileManager" in source


def test_the_composition_root_initializes_no_retired_manager():
    source = (PKG / "core" / "app_controller.py").read_text(encoding="utf-8")
    for name in RETIRED_CLASSES:
        assert f"{name}.initialize(" not in source
        assert f"import {name}\n" not in source


def test_the_composition_root_keeps_no_orphaned_manager_attribute():
    source = (PKG / "core" / "app_controller.py").read_text(encoding="utf-8")
    for attribute in (
        "self.room_info_window",
        "self.topic_manager",
        "self.notice_manager",
        "self.recommendation_manager",
        "self.room_name_manager",
    ):
        assert attribute not in source


def test_importing_the_room_profile_module_pulls_in_no_retired_manager():
    probe = (
        "import json, sys\n"
        "import ushareiplay.modules.room.room_profile\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('ushareiplay'))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(SRC.parent),
        check=False,
    )
    assert result.returncode == 0, f"导入房间档案失败：\n{result.stderr}"

    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    retired = sorted(
        f"ushareiplay.managers.{m}" for m in RETIRED_MODULES if f"ushareiplay.managers.{m}" in loaded
    )
    assert retired == []


def test_the_room_profile_modules_have_no_deferred_imports():
    for path in _python_sources(PKG / "modules" / "room"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    offenders.append(f"{path.relative_to(SRC)}:{sub.lineno}")
        assert offenders == [], offenders


def test_the_singleton_contract_test_names_no_retired_class():
    source = (pathlib.Path(__file__).resolve().parent / "test_singleton.py").read_text(
        encoding="utf-8"
    )
    for name in RETIRED_CLASSES:
        assert name not in source


@pytest.mark.parametrize(
    "doc",
    [
        "AGENTS.md",
        "GLOSSARY.md",
        "docs/room.md",
        "docs/adr/0001-room-name-deep-module.md",
        "docs/adr/0009-composition-root-dependency-injection-and-singleton-contract.md",
    ],
)
def test_live_docs_do_not_list_a_retired_manager_as_a_current_component(doc):
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / doc).read_text(encoding="utf-8")

    deleted_markers = ("已", "deleted", "was a", "folded into", "consolidated")
    for line in text.splitlines():
        if "RoomInfoWindow" in line:
            assert any(marker in line for marker in deleted_markers), (
                f"{doc} 仍把 RoomInfoWindow 当作现存组件: {line.strip()}"
            )

    for line in text.splitlines():
        if line.lstrip().startswith(("|", "├──", "└──", "│")):
            for name in RETIRED_CLASSES:
                assert name not in line, f"{doc} 的组件表仍列着已删除的 {name}: {line.strip()}"
