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

from e2e_coordination import (
    LeaseConflict,
    acquire_lease,
    discover_local_sessions,
    load_remote_target,
    release_lease,
    remote_command,
    terminate_sessions,
    transfer_lease_owner,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
AGENT_DIR = REPO_ROOT / ".agent"
PID_FILE = AGENT_DIR / "ushareiplay.pid"
COMMAND_DIR = AGENT_DIR / "commands"
EVOLUTION_LOG = AGENT_DIR / "e2e-toolbelt-evolution.jsonl"
CONFIG_LOCAL = REPO_ROOT / "config.local.yaml"
REMOTE_SESSION_FILE = AGENT_DIR / "remote-session.json"


def _now() -> float:
    return time.time()


def _run(cmd: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


def _device_id(args: argparse.Namespace) -> str:
    if getattr(args, "device_id", ""):
        return args.device_id
    try:
        import yaml

        for path in (CONFIG_LOCAL, REPO_ROOT / "config.yaml"):
            if not path.exists():
                continue
            config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            name = config.get("device", {}).get("name")
            if isinstance(name, str) and name:
                return name
    except Exception:
        pass
    raise RuntimeError("device id is required: configure device.name or pass --device-id")


def _cleanup_local_sessions(args: argparse.Namespace) -> list[dict[str, Any]]:
    sessions = discover_local_sessions(_device_id(args))
    if not sessions:
        return []
    remaining = terminate_sessions(sessions, timeout_s=args.stop_timeout, force=True)
    if remaining:
        raise RuntimeError(f"local E2E sessions remain after cleanup: {json.dumps(remaining, ensure_ascii=False)}")
    return sessions


def _remote_target():
    target = load_remote_target(CONFIG_LOCAL)
    if not target:
        raise RuntimeError("remote configuration missing: add agent_e2e.remote.host and deploy_path to config.local.yaml")
    return target


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _managed_pid() -> int | None:
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        if raw[:1] == "{":
            obj = json.loads(raw)
            pid = obj.get("pid")
            return int(pid) if pid is not None else None
        return int(raw)
    except Exception:
        return None


def _managed_pgid() -> int | None:
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        if raw[:1] == "{":
            obj = json.loads(raw)
            pgid = obj.get("pgid")
            return int(pgid) if pgid is not None else None
    except Exception:
        return None
    return None


def _managed_session() -> tuple[str | None, str | None]:
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        obj = json.loads(raw) if raw.startswith("{") else {}
        return obj.get("session_id"), obj.get("device_id")
    except Exception:
        return None, None


def _safe_getpgid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except Exception:
        return None


def _kill_group(pgid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pgid, sig)
    except Exception:
        pass


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
    resolved_pgid = _managed_pgid() or _safe_getpgid(pid) or pid
    _kill_group(resolved_pgid, signal.SIGINT)
    deadline = _now() + timeout_s
    while _now() < deadline:
        if not _pid_alive(pid):
            PID_FILE.unlink(missing_ok=True)
            return
        time.sleep(0.2)
    _kill_group(resolved_pgid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)


def cmd_stop(args: argparse.Namespace) -> int:
    session_id, device_id = _managed_session()
    _stop(args.timeout)
    if session_id and device_id:
        release_lease(device_id, session_id=session_id)
    return cmd_process_status(args)


def _list_repo_ushareiplay_pids() -> list[int]:
    """
    Best-effort: find all ushareiplay processes started from this repo root.
    This catches orphaned instances started outside the managed PID file.
    """
    needles = [
        str(REPO_ROOT / ".venv" / "bin" / "ushareiplay"),
        f"uv run ushareiplay",
    ]
    pids: set[int] = set()
    for needle in needles:
        try:
            # pgrep -f matches full command line
            r = _run(["pgrep", "-f", needle], timeout=5)
            if r.returncode != 0:
                continue
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    pids.add(int(line))
                except Exception:
                    continue
        except Exception:
            continue
    return sorted(pids)


def cmd_stop_all(args: argparse.Namespace) -> int:
    """
    Stop any ushareiplay instances likely belonging to this repo, not only the managed pid.
    """
    # First try the managed stop path (kills process group).
    _stop(args.timeout)

    # Then cleanup any orphaned instances started outside the PID file.
    pids = _list_repo_ushareiplay_pids()
    if not pids:
        return cmd_process_status(args)

    # kill as process groups when possible
    for pid in pids:
        if not _pid_alive(pid):
            continue
        pgid = _safe_getpgid(pid) or pid
        _kill_group(pgid, signal.SIGINT)

    deadline = _now() + args.timeout
    while _now() < deadline:
        alive = [pid for pid in pids if _pid_alive(pid)]
        if not alive:
            return cmd_process_status(args)
        time.sleep(0.2)

    for pid in pids:
        if not _pid_alive(pid):
            continue
        pgid = _safe_getpgid(pid) or pid
        _kill_group(pgid, signal.SIGKILL)

    return cmd_process_status(args)


def cmd_cleanup_local(args: argparse.Namespace) -> int:
    cleaned = _cleanup_local_sessions(args)
    print(json.dumps({"device_id": _device_id(args), "cleaned": cleaned}, ensure_ascii=False, indent=2))
    return 0


def _run_remote(action: str) -> subprocess.CompletedProcess[str]:
    return _run(remote_command(_remote_target(), action), timeout=30)


def cmd_remote_status(_: argparse.Namespace) -> int:
    result = _run_remote("status")
    print(result.stdout.rstrip())
    return result.returncode


def cmd_remote_pause(_: argparse.Namespace) -> int:
    result = _run_remote("pause")
    payload = {
        "target": _remote_target().host,
        "deploy_path": _remote_target().deploy_path,
        "paused_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "pause_output": result.stdout,
    }
    if result.returncode == 0:
        AGENT_DIR.mkdir(parents=True, exist_ok=True)
        REMOTE_SESSION_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return result.returncode


def cmd_remote_force_stop(args: argparse.Namespace) -> int:
    if not args.confirm:
        print("remote force-stop requires --confirm", file=sys.stderr)
        return 2
    result = _run_remote("force-stop")
    print(result.stdout.rstrip())
    return result.returncode


def cmd_remote_resume(_: argparse.Namespace) -> int:
    if not REMOTE_SESSION_FILE.exists():
        print("remote resume requires a successful remote-pause from this E2E session", file=sys.stderr)
        return 2
    receipt = json.loads(REMOTE_SESSION_FILE.read_text(encoding="utf-8"))
    target = _remote_target()
    if receipt.get("target") != target.host or receipt.get("deploy_path") != target.deploy_path:
        print("remote target changed since pause; refusing automatic resume", file=sys.stderr)
        return 2
    result = _run_remote("resume")
    print(result.stdout.rstrip())
    if result.returncode == 0:
        REMOTE_SESSION_FILE.unlink(missing_ok=True)
    return result.returncode


def cmd_remote_logs(args: argparse.Namespace) -> int:
    result = _run_remote("logs")
    if result.returncode:
        print(result.stdout.rstrip(), file=sys.stderr)
        return result.returncode
    run_id = datetime.now(timezone.utc).strftime("remote-logs-%Y%m%dT%H%M%SZ")
    out = ARTIFACTS_ROOT / run_id / "remote-log-files.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.stdout, encoding="utf-8")
    files = [line.removeprefix("==> ") for line in result.stdout.splitlines() if line.startswith("==> ")]
    print(json.dumps({"remote": _remote_target().host, "captured_at": datetime.now(timezone.utc).isoformat(), "path": str(out), "files": files, "bytes": len(result.stdout.encode("utf-8"))}, ensure_ascii=False, indent=2))
    return 0

def cmd_start(args: argparse.Namespace) -> int:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = _cleanup_local_sessions(args)
    session_id = uuid.uuid4().hex
    try:
        lease = acquire_lease(_device_id(args), session_id=session_id, worktree=str(REPO_ROOT))
    except LeaseConflict as exc:
        raise RuntimeError(f"device remains leased after cleanup: {json.dumps(exc.lease, ensure_ascii=False)}") from exc
    pid = _managed_pid()
    if args.scenario == "dev":
        _stop(args.stop_timeout)
    elif pid and _pid_alive(pid):
        lease = transfer_lease_owner(_device_id(args), session_id=session_id, owner_pid=pid)
        print(json.dumps({"action": "reused", "pid": pid, "session_id": session_id, "lease": lease, "cleaned": cleaned}, ensure_ascii=False))
        return 0

    log_path = AGENT_DIR / "run.log"
    log = log_path.open("ab")
    proc = subprocess.Popen(
        ["bash", "-lc", "./run.sh"],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pgid = proc.pid
    lease = transfer_lease_owner(_device_id(args), session_id=session_id, owner_pid=proc.pid)
    PID_FILE.write_text(json.dumps({"pid": proc.pid, "pgid": pgid, "session_id": session_id, "device_id": _device_id(args)}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"action": "started", "pid": proc.pid, "log": str(log_path), "session_id": session_id, "lease": lease, "cleaned": cleaned}, ensure_ascii=False))
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
    p.add_argument("--device-id", default="", help="Shared Android device identifier; defaults to device.name")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("stop")
    p.add_argument("--timeout", type=float, default=8.0)
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("stop-all")
    p.add_argument("--timeout", type=float, default=8.0)
    p.set_defaults(func=cmd_stop_all)

    p = sub.add_parser("cleanup-local")
    p.add_argument("--device-id", default="", help="Shared Android device identifier; defaults to device.name")
    p.add_argument("--stop-timeout", type=float, default=8.0)
    p.set_defaults(func=cmd_cleanup_local)

    sub.add_parser("remote-status").set_defaults(func=cmd_remote_status)
    sub.add_parser("remote-pause").set_defaults(func=cmd_remote_pause)
    p = sub.add_parser("remote-force-stop")
    p.add_argument("--confirm", action="store_true", help="Required after reporting a failed remote pause")
    p.set_defaults(func=cmd_remote_force_stop)
    sub.add_parser("remote-resume").set_defaults(func=cmd_remote_resume)
    sub.add_parser("remote-logs").set_defaults(func=cmd_remote_logs)

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
