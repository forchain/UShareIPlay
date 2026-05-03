"""
E2E-style regression for logging.directory (especially ../logs).

Regression source: commit that introduced safe_workspace_path redirected ../logs
into <repo>/logs, so files never appeared under the parent directory. This test
reproduces that layout in a temp tree and asserts the log file lands where config points.
"""
from __future__ import annotations

import logging
from pathlib import Path


def test_resolve_log_directory_keeps_parent_path(tmp_path: Path, monkeypatch) -> None:
    """../logs 必须解析到仓库上一级（与“安全重定向到仓库内”不同）。"""
    project = tmp_path / "repo"
    project.mkdir()
    (project / "src").mkdir()
    (project / "config.yaml").write_text("", encoding="utf-8")
    monkeypatch.chdir(project)

    from ushareiplay.core.paths import repo_root, resolve_log_directory, safe_workspace_path

    assert repo_root().resolve() == project.resolve()

    resolved = resolve_log_directory("../logs", default_rel="logs")
    assert resolved == (tmp_path / "logs").resolve()

    redirected = safe_workspace_path("../logs", default_rel="logs")
    assert redirected == (project / "logs").resolve()
    assert redirected != resolved


def test_probe_log_file_written_next_to_repo_not_inside(tmp_path: Path, monkeypatch) -> None:
    """模拟 AppHandler / chat 使用的路径链：配置 ../logs 时探针文件写在上一级 logs。"""
    project = tmp_path / "worktree"
    project.mkdir()
    (project / "src").mkdir()
    (project / "config.yaml").write_text(
        "logging:\n  directory: ../logs\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    from ushareiplay.core.config_loader import ConfigLoader
    from ushareiplay.core.paths import ensure_dir, resolve_log_directory

    cfg = ConfigLoader.load_config("config.yaml")
    raw = ((cfg or {}).get("logging", {}) or {}).get("directory", "")
    log_dir = ensure_dir(resolve_log_directory(raw, default_rel="logs"))
    probe = log_dir / "e2e_probe.log"
    probe.write_text("ok\n", encoding="utf-8")

    assert probe.exists()
    assert probe.resolve().parent == (tmp_path / "logs").resolve()
    assert not (project / "logs" / "e2e_probe.log").exists()


def test_filehandler_writes_resolved_log_directory(tmp_path: Path, monkeypatch) -> None:
    """与真实 logging.FileHandler 一致：目录与文件落在解析后的路径。"""
    project = tmp_path / "myrepo"
    project.mkdir()
    (project / "src").mkdir()
    (project / "config.yaml").write_text(
        "logging:\n  directory: ../logs\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    from ushareiplay.core.config_loader import ConfigLoader
    from ushareiplay.core.paths import ensure_dir, resolve_log_directory

    cfg = ConfigLoader.load_config("config.yaml")
    raw = ((cfg or {}).get("logging", {}) or {}).get("directory", "")
    log_dir = ensure_dir(resolve_log_directory(raw, default_rel="logs"))
    log_file = log_dir / "handler_test.log"

    logger = logging.getLogger("e2e_handler_test")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(fh)
    logger.info("line")
    fh.close()

    assert log_file.read_text(encoding="utf-8").strip() == "line"
    assert log_file.resolve().parent == (tmp_path / "logs").resolve()
