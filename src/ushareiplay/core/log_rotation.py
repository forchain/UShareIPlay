from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def _log_file_created_at(path: Path) -> datetime:
    stat_result = path.stat()
    timestamp = getattr(stat_result, "st_birthtime", None)
    if timestamp is None:
        timestamp = stat_result.st_mtime
    return datetime.fromtimestamp(timestamp)


def _archive_path(log_dir: Path, active_name: str, created_at: datetime) -> Path:
    active_path = Path(active_name)
    stem = active_path.stem
    suffix = active_path.suffix
    timestamp = created_at.strftime("%Y-%m-%d_%H-%M-%S")
    return log_dir / f"{stem}_{timestamp}{suffix}"


def archive_active_log_on_startup(log_dir: Path, active_name: str) -> Path:
    """
    Archive a fixed active log file at logger startup.

    The archive filename uses the active file's creation time to the second.
    When the platform does not expose creation time, modification time is used.
    Missing files are left in place.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    active_path = log_dir / active_name
    if not active_path.exists():
        return active_path

    archive_path = _archive_path(log_dir, active_name, _log_file_created_at(active_path))
    os.replace(active_path, archive_path)
    active_path.touch()
    return active_path
