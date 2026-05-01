#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
AGENT_DIR = REPO_ROOT / ".agent"
PID_FILE = AGENT_DIR / "ushareiplay.pid"
COMMAND_DIR = AGENT_DIR / "commands"
EVOLUTION_LOG = AGENT_DIR / "e2e-toolbelt-evolution.jsonl"


def _now() -> float:
    return time.time()


def _run(cmd: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _managed_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _latest_run_dir() -> Path | None:
    if not ARTIFACTS_ROOT.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for path in ARTIFACTS_ROOT.iterdir():
        if not path.is_dir():
            continue
        status = path / "status.json"
        events = path / "events.jsonl"
        if not status.exists() or not events.exists():
            continue
        candidates.append((max(status.stat().st_mtime, events.stat().st_mtime), path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except Exception:
                continue


def cmd_process_status(_: argparse.Namespace) -> int:
    pid = _managed_pid()
    run_dir = _latest_run_dir()
    payload = {
        "pid": pid,
        "alive": bool(pid and _pid_alive(pid)),
        "pid_file": str(PID_FILE),
        "latest_run_dir": str(run_dir) if run_dir else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _check_path(path: Path, *, kind: str = "exists") -> dict[str, Any]:
    if kind == "file":
        ok = path.is_file()
    elif kind == "dir":
        ok = path.is_dir()
    else:
        ok = path.exists()
    return {"path": str(path), "ok": ok}


def cmd_doctor(args: argparse.Namespace) -> int:
    needs = {item.strip() for part in args.needs for item in part.split(",") if item.strip()}
    checks: dict[str, Any] = {
        "repo_root": str(REPO_ROOT),
        "needs": sorted(needs),
        "shared": {
            "config_yaml": _check_path(REPO_ROOT / "config.yaml", kind="file"),
            "config_local_yaml": _check_path(REPO_ROOT / "config.local.yaml", kind="file"),
            "venv": _check_path(REPO_ROOT / ".venv"),
            "run_sh": _check_path(REPO_ROOT / "run.sh", kind="file"),
        },
        "capabilities": {},
    }

    if "process" in needs:
        pid = _managed_pid()
        checks["capabilities"]["process"] = {
            "pid": pid,
            "alive": bool(pid and _pid_alive(pid)),
            "run_sh_executable": os.access(REPO_ROOT / "run.sh", os.X_OK),
        }

    if "input" in needs:
        COMMAND_DIR.mkdir(parents=True, exist_ok=True)
        probe = COMMAND_DIR / ".doctor"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable = True
            error = ""
        except Exception as exc:
            writable = False
            error = str(exc)
        checks["capabilities"]["input"] = {"command_dir": str(COMMAND_DIR), "writable": writable, "error": error}

    if "adb" in needs:
        adb_path = shutil.which("adb")
        adb_result = None
        if adb_path:
            result = _run(["adb", "devices"], timeout=10)
            adb_result = {"returncode": result.returncode, "output": result.stdout.strip()}
        checks["capabilities"]["adb"] = {"adb_path": adb_path, "devices": adb_result}

    if "db" in needs:
        db = REPO_ROOT / args.db
        readable = db.exists() and os.access(db, os.R_OK)
        checks["capabilities"]["db"] = {"path": str(db), "exists": db.exists(), "readable": readable}

    if "logs" in needs:
        logs = REPO_ROOT / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        checks["capabilities"]["logs"] = {"path": str(logs), "exists": logs.exists(), "writable": os.access(logs, os.W_OK)}

    if "artifacts" in needs:
        ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
        latest = _latest_run_dir()
        checks["capabilities"]["artifacts"] = {
            "path": str(ARTIFACTS_ROOT),
            "exists": ARTIFACTS_ROOT.exists(),
            "writable": os.access(ARTIFACTS_ROOT, os.W_OK),
            "latest_run_dir": str(latest) if latest else None,
        }

    failed = []
    shared = checks["shared"]
    if not shared["config_yaml"]["ok"]:
        failed.append("missing config.yaml")
    if not shared["run_sh"]["ok"]:
        failed.append("missing run.sh")
    for name, cap in checks["capabilities"].items():
        if name == "input" and not cap["writable"]:
            failed.append("input spool not writable")
        if name == "adb" and (not cap["adb_path"] or not cap["devices"] or cap["devices"]["returncode"] != 0):
            failed.append("adb unavailable")
        if name == "db" and not cap["readable"]:
            failed.append("db unavailable")
        if name in ("logs", "artifacts") and not cap["writable"]:
            failed.append(f"{name} not writable")

    checks["ok"] = not failed
    checks["failed"] = failed
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["ok"] else 2


def _stop(timeout_s: float) -> None:
    pid = _managed_pid()
    if not pid:
        return
    if not _pid_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGINT)
    except Exception:
        pass
    deadline = _now() + timeout_s
    while _now() < deadline:
        if not _pid_alive(pid):
            PID_FILE.unlink(missing_ok=True)
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
    PID_FILE.unlink(missing_ok=True)


def cmd_stop(args: argparse.Namespace) -> int:
    _stop(args.timeout)
    return cmd_process_status(args)


def cmd_start(args: argparse.Namespace) -> int:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    pid = _managed_pid()
    if args.scenario == "dev":
        _stop(args.stop_timeout)
    elif pid and _pid_alive(pid):
        print(json.dumps({"action": "reused", "pid": pid}, ensure_ascii=False))
        return 0

    log_path = AGENT_DIR / "run.log"
    log = log_path.open("ab")
    proc = subprocess.Popen(
        ["bash", "-lc", "./run.sh"],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    print(json.dumps({"action": "started", "pid": proc.pid, "log": str(log_path)}, ensure_ascii=False))
    return 0


def cmd_inject(args: argparse.Namespace) -> int:
    COMMAND_DIR.mkdir(parents=True, exist_ok=True)
    target = COMMAND_DIR / f"{int(_now() * 1000)}-{uuid.uuid4().hex[:8]}.cmd"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(args.text.rstrip("\n") + "\n", encoding="utf-8")
    tmp.replace(target)
    print(json.dumps({"path": str(target), "text": args.text}, ensure_ascii=False))
    return 0


def cmd_request_dump(_: argparse.Namespace) -> int:
    return cmd_inject(argparse.Namespace(text="!dump"))


def cmd_adb_devices(_: argparse.Namespace) -> int:
    result = _run(["adb", "devices"], timeout=10)
    print(result.stdout.rstrip())
    return result.returncode


def cmd_adb_current(_: argparse.Namespace) -> int:
    result = _run(["adb", "shell", "dumpsys", "window"], timeout=15)
    if result.returncode != 0:
        print(result.stdout.rstrip())
        return result.returncode
    lines = []
    for line in result.stdout.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            lines.append(line.strip())
    print("\n".join(lines) if lines else result.stdout[-2000:])
    return 0


def cmd_adb_screenshot(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["adb", "exec-out", "screencap", "-p"], cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
        return result.returncode
    out.write_bytes(result.stdout)
    print(str(out))
    return 0


def cmd_adb_logcat(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    result = _run(["adb", "logcat", "-d", "-t", str(args.lines)], timeout=args.seconds)
    out.write_text(result.stdout, encoding="utf-8")
    print(str(out))
    return result.returncode


def cmd_artifacts_latest(_: argparse.Namespace) -> int:
    run_dir = _latest_run_dir()
    if not run_dir:
        print(json.dumps({"latest_run_dir": None}, ensure_ascii=False, indent=2))
        return 1
    payload = {
        "latest_run_dir": str(run_dir),
        "status_json": str(run_dir / "status.json"),
        "events_jsonl": str(run_dir / "events.jsonl"),
        "page_source_xml": str(run_dir / "page_source.xml"),
        "screenshot_png": str(run_dir / "screenshot.png"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_read_status(_: argparse.Namespace) -> int:
    run_dir = _latest_run_dir()
    if not run_dir:
        print("no artifacts run found", file=sys.stderr)
        return 1
    print((run_dir / "status.json").read_text(encoding="utf-8"))
    return 0


def cmd_tail_events(args: argparse.Namespace) -> int:
    run_dir = _latest_run_dir()
    if not run_dir:
        print("no artifacts run found", file=sys.stderr)
        return 1
    events = list(_iter_jsonl(run_dir / "events.jsonl"))
    for evt in events[-args.limit:]:
        print(json.dumps(evt, ensure_ascii=False))
    return 0


def cmd_tail_logs(args: argparse.Namespace) -> int:
    logs = sorted((REPO_ROOT / "logs").rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True) if (REPO_ROOT / "logs").exists() else []
    pattern = re.compile(args.pattern) if args.pattern else None
    for path in logs[: args.files]:
        text = path.read_text(encoding="utf-8", errors="replace")[-args.chars :]
        if pattern and not pattern.search(text):
            continue
        print(f"==> {path}")
        print(text)
    return 0


def cmd_db_query(args: argparse.Namespace) -> int:
    db = Path(args.db)
    if not db.is_absolute():
        db = REPO_ROOT / db
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(args.sql).fetchall()
    finally:
        conn.close()
    print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_record_gap(args: argparse.Namespace) -> int:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "kind": args.kind,
        "title": args.title,
        "detail": args.detail,
        "suggested_next": args.suggested_next,
    }
    with EVOLUTION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(json.dumps({"recorded": str(EVOLUTION_LOG), **payload}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Business-neutral E2E toolbelt for UShareIPlay agents.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor")
    p.add_argument("--needs", action="append", default=["process,artifacts,logs"])
    p.add_argument("--db", default="data/soul_bot.db")
    p.set_defaults(func=cmd_doctor)

    sub.add_parser("process-status").set_defaults(func=cmd_process_status)

    p = sub.add_parser("start")
    p.add_argument("--scenario", choices=["dev", "test"], default="test")
    p.add_argument("--stop-timeout", type=float, default=8.0)
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("stop")
    p.add_argument("--timeout", type=float, default=8.0)
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("inject")
    p.add_argument("--text", required=True)
    p.set_defaults(func=cmd_inject)

    sub.add_parser("request-dump").set_defaults(func=cmd_request_dump)
    sub.add_parser("adb-devices").set_defaults(func=cmd_adb_devices)
    sub.add_parser("adb-current").set_defaults(func=cmd_adb_current)

    p = sub.add_parser("adb-screenshot")
    p.add_argument("--out", default=".agent/adb-screenshot.png")
    p.set_defaults(func=cmd_adb_screenshot)

    p = sub.add_parser("adb-logcat")
    p.add_argument("--out", default=".agent/adb-logcat.txt")
    p.add_argument("--lines", type=int, default=1000)
    p.add_argument("--seconds", type=float, default=15.0)
    p.set_defaults(func=cmd_adb_logcat)

    sub.add_parser("artifacts-latest").set_defaults(func=cmd_artifacts_latest)
    sub.add_parser("read-status").set_defaults(func=cmd_read_status)

    p = sub.add_parser("tail-events")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_tail_events)

    p = sub.add_parser("tail-logs")
    p.add_argument("--pattern", default="")
    p.add_argument("--files", type=int, default=3)
    p.add_argument("--chars", type=int, default=12000)
    p.set_defaults(func=cmd_tail_logs)

    p = sub.add_parser("db-query")
    p.add_argument("--db", default="data/soul_bot.db")
    p.add_argument("--sql", required=True)
    p.set_defaults(func=cmd_db_query)

    p = sub.add_parser("record-gap")
    p.add_argument(
        "--kind",
        choices=["missing-tool", "repeatable-flow", "temporary-helper", "testability-gap", "architecture-upgrade"],
        required=True,
    )
    p.add_argument("--title", required=True)
    p.add_argument("--detail", required=True)
    p.add_argument("--suggested-next", default="")
    p.set_defaults(func=cmd_record_gap)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
