from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def repo_root() -> Path:
    # Best-effort: project uses "run from workspace root" imports (src.*),
    # so cwd is typically repo root. Fall back to walking up from this file.
    cwd = Path.cwd().resolve()
    if (cwd / "config.yaml").exists() and (cwd / "src").exists():
        return cwd

    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / "config.yaml").exists() and (parent / "src").exists():
            return parent
    return cwd


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def safe_workspace_path(configured: str, default_rel: str) -> Path:
    """
    Normalize a configured directory path to a workspace-safe location.

    If the configured path escapes repo root (e.g. '../logs'), it will be
    redirected to a safe default under repo root.
    """
    root = repo_root()
    raw = (configured or "").strip()
    if not raw:
        return (root / default_rel).resolve()

    p = Path(raw)
    resolved = (p if p.is_absolute() else (root / p)).resolve()
    if _is_within(resolved, root):
        return resolved
    return (root / default_rel).resolve()


@dataclass(frozen=True)
class ArtifactsPaths:
    root: Path
    run_dir: Path
    events_jsonl: Path
    status_json: Path
    page_source_xml: Path
    screenshot_png: Path


def artifacts_paths(run_id: str, root_rel: str = "artifacts") -> ArtifactsPaths:
    root = ensure_dir((repo_root() / root_rel).resolve())
    run_dir = ensure_dir((root / run_id).resolve())
    return ArtifactsPaths(
        root=root,
        run_dir=run_dir,
        events_jsonl=run_dir / "events.jsonl",
        status_json=run_dir / "status.json",
        page_source_xml=run_dir / "page_source.xml",
        screenshot_png=run_dir / "screenshot.png",
    )

