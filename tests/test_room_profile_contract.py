"""收口契约：房间档案只剩一个模块，遗留单例与它们的循环边已经不在代码里。

这是 spec #387 第六张票（#394）专属的一组「缺席断言」。前面五张票证明的是
`RoomProfileManager` 能干活；这一张证明的是**旧的活法已经彻底消失**：

- `room_info_window.py` 这个过渡门面连同它的类一起没了
- `src/` 下再没有一处提到它
- 组合根只为房间档案注册**一个**单例
- `import room_profile` 不会把任何已下线的管理器拖进来
- `room_profile` 内部没有为了绕开循环而写的 manager→manager 延迟导入

前四条靠源码与文件系统断言，最后一条靠子进程里的真实 import 图 —— 因为
「循环是否闭合」只有在解释器真的把模块导入一遍时才作数。
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


# --------------------------------------------------------------------------
# 1. 门面连同文件一起消失
# --------------------------------------------------------------------------


def test_the_room_info_window_shim_file_is_gone():
    shim = PKG / "managers" / "room_info_window.py"
    assert not shim.exists(), f"过渡门面必须删除：{shim} 仍在"


def test_the_room_info_window_shim_is_not_importable():
    import importlib.util

    assert importlib.util.find_spec("ushareiplay.managers.room_info_window") is None, (
        "模块已从磁盘删除，却仍可被 import 解析出来（多半是 __pycache__ 残留）"
    )


@pytest.mark.parametrize("module", RETIRED_MODULES)
def test_every_retired_manager_module_is_gone(module):
    assert not (PKG / "managers" / f"{module}.py").exists()


# --------------------------------------------------------------------------
# 2. src/ 下再没有一处提到门面
# --------------------------------------------------------------------------


def test_no_source_module_mentions_the_retired_shim():
    """门面删掉却还有调用点，就是活调用点漏网 —— 逐个文件按源码查。"""
    offenders = []
    for path in _python_sources(PKG):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "RoomInfoWindow" in line or "room_info_window" in line:
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
    assert offenders == [], "以下位置仍在引用已删除的门面：\n" + "\n".join(offenders)


@pytest.mark.parametrize("name", RETIRED_CLASSES)
def test_no_source_module_imports_a_retired_manager(name):
    offenders = []
    for path in _python_sources(PKG):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 源码本身就坏了才走到这里
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", None) or ""
                names = " ".join(alias.name for alias in node.names)
                if name in module or name in names:
                    offenders.append(f"{path.relative_to(SRC)}: {module or names}")
    assert offenders == [], f"{name} 已被删除，却仍被 import：\n" + "\n".join(offenders)


# --------------------------------------------------------------------------
# 3. 组合根只注册一个房间档案单例
# --------------------------------------------------------------------------


def _app_controller_source() -> str:
    return (PKG / "core" / "app_controller.py").read_text(encoding="utf-8")


def test_the_composition_root_registers_exactly_one_room_profile_singleton():
    source = _app_controller_source()
    initializations = source.count("RoomProfileManager.initialize(")
    assert initializations == 1, (
        f"组合根必须恰好注册一个房间档案单例，实际 {initializations} 次"
    )
    assert "self.room_profile_manager = RoomProfileManager.initialize(" in source, (
        "房间档案单例必须由组合根持有（ADR-0009 §1）"
    )


def test_the_composition_root_initializes_no_retired_manager():
    source = _app_controller_source()
    for name in RETIRED_CLASSES:
        assert f"{name}.initialize(" not in source, (
            f"组合根仍在初始化已删除的 {name}"
        )
        assert f"import {name}\n" not in source, (
            f"组合根仍顶层 import 已删除的 {name}"
        )


def test_the_composition_root_keeps_no_orphaned_manager_attribute():
    """#390~#393 陆续删掉了 controller 上的遗留属性，这里钉住它不再长回来。"""
    source = _app_controller_source()
    for attribute in (
        "self.room_info_window",
        "self.topic_manager",
        "self.notice_manager",
        "self.recommendation_manager",
        "self.room_name_manager",
    ):
        assert attribute not in source, f"组合根残留已无人使用的属性 {attribute}"


# --------------------------------------------------------------------------
# 4. import room_profile 不会拖进任何已下线的管理器
# --------------------------------------------------------------------------


def test_importing_room_profile_pulls_in_no_retired_manager():
    """在一个干净的子进程里真导入一次，看 sys.modules 里有没有遗留模块。"""
    probe = (
        "import json, sys\n"
        "import ushareiplay.managers.room_profile\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('ushareiplay'))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(SRC.parent),
        check=False,
    )
    assert result.returncode == 0, f"导入 room_profile 失败：\n{result.stderr}"

    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    retired = sorted(
        f"ushareiplay.managers.{m}"
        for m in RETIRED_MODULES
        if f"ushareiplay.managers.{m}" in loaded
    )
    assert retired == [], f"导入房间档案拖进了已下线的模块：{retired}"


def test_the_room_profile_package_does_not_import_the_room_profile_shim():
    """反向再钉一次：抽屉会话的真正所有者不能回头依赖门面。"""
    for path in _python_sources(PKG / "managers" / "room_profile"):
        text = path.read_text(encoding="utf-8")
        assert "room_info_window" not in text, path


# --------------------------------------------------------------------------
# 5. room_profile 内部没有 manager → manager 延迟导入
# --------------------------------------------------------------------------


def test_room_profile_has_no_deferred_manager_to_manager_import():
    """循环边闭合的判据：函数体里不得再 import 别的 manager。

    剩下的只有 `MessageDispatch`（core 层，不是 manager），那是单向依赖。
    """
    offenders = []
    for path in _python_sources(PKG / "managers" / "room_profile"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, (ast.Import, ast.ImportFrom)):
                    continue
                module = getattr(sub, "module", None) or ""
                names = " ".join(alias.name for alias in getattr(sub, "names", []))
                target = f"{module} {names}".strip()
                if "ushareiplay.managers." in target:
                    offenders.append(
                        f"{path.relative_to(SRC)}:{sub.lineno}: {target}"
                    )
    assert offenders == [], (
        "房间档案模块里仍为了绕开循环而延迟导入 manager：\n" + "\n".join(offenders)
    )


def test_room_profile_has_no_deferred_import_at_all():
    """#394 收口的字面要求：房间档案模块里**一处**延迟导入都不许留。

    上一条只查 manager → manager 的边，因此 core 层的 `MessageDispatch` 逃过一劫。
    这里是更强的判据：任何函数体里的 import 都不合法，因为模块边已经理顺到
    可以顶层导入了。真的出现循环时，`_import_cycle_facts` 那个测试会先炸。
    """
    offenders = []
    for path in _python_sources(PKG / "managers" / "room_profile"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    module = getattr(sub, "module", None) or ""
                    names = " ".join(alias.name for alias in getattr(sub, "names", []))
                    offenders.append(
                        f"{path.relative_to(SRC)}:{sub.lineno}: {f'{module} {names}'.strip()}"
                    )
    assert offenders == [], (
        "房间档案模块里仍留着延迟导入（应提升到模块顶层）：\n" + "\n".join(offenders)
    )


def test_the_deferred_import_removal_is_safe_because_the_import_graph_is_acyclic():
    """把「为什么敢顶层导入」钉成断言，而不是留在评审记录里。

    做法是问解释器：真导入一遍房间档案之后，`MessageDispatch` 及其传递依赖必须
    **已经**在 `sys.modules` 里，且它们不反向依赖房间档案。前者证明不需要延迟，
    后者证明没有循环。
    """
    probe = (
        "import json, sys\n"
        "import ushareiplay.managers.room_profile.manager\n"
        "loaded = sorted(m for m in sys.modules if m.startswith('ushareiplay'))\n"
        "deps = [m for m in loaded if m in (\n"
        "    'ushareiplay.core.message_dispatch',\n"
        "    'ushareiplay.managers.user_manager',\n"
        ")]\n"
        "print(json.dumps({\n"
        "    'deps': deps,\n"
        "    'room_profile_loaded': any(\n"
        "        m.startswith('ushareiplay.managers.room_profile') for m in loaded\n"
        "    ),\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(SRC.parent),
        check=False,
    )
    assert result.returncode == 0, f"导入房间档案失败：\n{result.stderr}"

    facts = json.loads(result.stdout.strip().splitlines()[-1])
    assert facts["deps"] == [
        "ushareiplay.core.message_dispatch",
        "ushareiplay.managers.user_manager",
    ], f"公屏依赖应当随房间档案一起顶层导入，实际 {facts['deps']}"


# --------------------------------------------------------------------------
# 6. ADR-0009 的受保护单例清单不再点名已删除的类
# --------------------------------------------------------------------------


def test_the_singleton_contract_test_names_no_retired_class():
    source = (pathlib.Path(__file__).resolve().parent / "test_singleton.py").read_text(
        encoding="utf-8"
    )
    for name in RETIRED_CLASSES:
        assert name not in source, f"test_singleton.py 仍在把 {name} 当作受保护单例"


# --------------------------------------------------------------------------
# 7. 活文档的组件表里不再列已删除的管理器
# --------------------------------------------------------------------------


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
    """只查「当前组件」的表述；`docs/superpowers/specs/` 下的历史设计稿保持原样。"""
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / doc).read_text(encoding="utf-8")

    # `RoomInfoWindow` 已彻底不存在：活文档若提到它，必须在同一句里说明它已下线。
    deleted_markers = ("已", "deleted", "was a", "folded into", "consolidated")
    for line in text.splitlines():
        if "RoomInfoWindow" in line:
            assert any(marker in line for marker in deleted_markers), (
                f"{doc} 仍把 RoomInfoWindow 当作现存组件（须在同一句注明已删除）: "
                f"{line.strip()}"
            )

    # 组件表 / 现状段落不得再把遗留管理器列为在册组件。
    for line in text.splitlines():
        if line.lstrip().startswith(("|", "├──", "└──", "│")):
            for name in RETIRED_CLASSES:
                assert name not in line, f"{doc} 的组件表仍列着已删除的 {name}: {line.strip()}"
