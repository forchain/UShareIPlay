#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
AGENT_DIR = REPO_ROOT / ".agent"
PID_FILE = AGENT_DIR / "ushareiplay.pid"
COMMAND_SPOOL_DIR = AGENT_DIR / "commands"


def _now() -> float:
    return time.time()


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path, *, offset: int = 0) -> Iterable[Tuple[int, Dict[str, Any]]]:
    """
    Iterate jsonl from a byte offset; yields (new_offset, obj).
    """
    with path.open("rb") as f:
        f.seek(offset)
        while True:
            line = f.readline()
            if not line:
                break
            offset = f.tell()
            try:
                obj = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            yield offset, obj


def _ensure_agent_dir() -> None:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    COMMAND_SPOOL_DIR.mkdir(parents=True, exist_ok=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_managed_pidfile() -> Tuple[Optional[int], Optional[int]]:
    """
    Backward compatible:
    - legacy: PID_FILE contains a plain integer pid
    - new: PID_FILE contains JSON like {"pid": 123, "pgid": 123}
    """
    if not PID_FILE.exists():
        return None, None
    raw = PID_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return None, None
    if raw[:1] == "{":
        try:
            obj = json.loads(raw)
            pid = int(obj.get("pid")) if obj.get("pid") is not None else None
            pgid = int(obj.get("pgid")) if obj.get("pgid") is not None else None
            return pid, pgid
        except Exception:
            return None, None
    try:
        pid = int(raw)
    except Exception:
        return None, None
    return pid, None


def _safe_getpgid(pid: int) -> Optional[int]:
    try:
        return os.getpgid(pid)
    except Exception:
        return None


def _kill_group(pgid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pgid, sig)
    except Exception:
        pass


def stop_existing(*, timeout_s: float = 8.0) -> None:
    if not PID_FILE.exists():
        return
    pid, pgid = _read_managed_pidfile()
    if pid is None:
        PID_FILE.unlink(missing_ok=True)
        return

    if not _pid_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return

    # Prefer killing the whole process group: run.sh / uv / python children must exit too.
    resolved_pgid = pgid or _safe_getpgid(pid) or pid
    _kill_group(resolved_pgid, signal.SIGINT)

    deadline = _now() + timeout_s
    while _now() < deadline:
        if not _pid_alive(pid):
            PID_FILE.unlink(missing_ok=True)
            return
        time.sleep(0.2)

    # hard kill
    _kill_group(resolved_pgid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)


def read_managed_pid() -> Optional[int]:
    pid, _pgid = _read_managed_pidfile()
    return pid


def is_managed_process_running() -> bool:
    pid = read_managed_pid()
    return bool(pid is not None and _pid_alive(pid))


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


def start_service() -> subprocess.Popen[bytes]:
    """
    Start service with stdin pipe so we can inject console commands.
    """
    proc = subprocess.Popen(
        ["bash", "-lc", "./run.sh"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(REPO_ROOT),
        start_new_session=True,
    )
    # New format: store pgid so stop can kill the entire subtree reliably.
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pgid = proc.pid
    PID_FILE.write_text(json.dumps({"pid": proc.pid, "pgid": pgid}, ensure_ascii=False), encoding="utf-8")
    return proc


def write_spool_command(line: str) -> Path:
    COMMAND_SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    target = COMMAND_SPOOL_DIR / f"{int(_now() * 1000)}-{uuid.uuid4().hex[:8]}.cmd"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(line.rstrip("\n") + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def git_has_uncommitted_changes() -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


def _prompt(text: str) -> str:
    if not sys.stdin.isatty():
        raise RuntimeError("缺少必要参数且当前非交互终端，无法提示输入。请显式传参。")
    return input(text).strip()


@dataclass(frozen=True)
class RunArtifacts:
    run_dir: Path
    events_jsonl: Path
    status_json: Path
    page_source_xml: Path
    screenshot_png: Path


def discover_run_artifacts(*, started_after: float, timeout_s: float) -> RunArtifacts:
    deadline = _now() + timeout_s
    while _now() < deadline:
        if ARTIFACTS_ROOT.exists():
            candidates: List[Tuple[float, Path]] = []
            for d in ARTIFACTS_ROOT.iterdir():
                if not d.is_dir():
                    continue
                status = d / "status.json"
                events = d / "events.jsonl"
                if status.exists() and events.exists():
                    try:
                        m = max(status.stat().st_mtime, events.stat().st_mtime)
                    except Exception:
                        continue
                    if m >= started_after:
                        candidates.append((m, d))
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                run_dir = candidates[0][1]
                return RunArtifacts(
                    run_dir=run_dir,
                    events_jsonl=run_dir / "events.jsonl",
                    status_json=run_dir / "status.json",
                    page_source_xml=run_dir / "page_source.xml",
                    screenshot_png=run_dir / "screenshot.png",
                )
        time.sleep(0.2)
    raise TimeoutError("在超时时间内未发现 artifacts/<run_id>/{events.jsonl,status.json}")


def discover_latest_run_artifacts(*, timeout_s: float = 2.0) -> RunArtifacts:
    """
    Best-effort: pick the most recently updated artifacts/<run_id> that has both files.
    """
    deadline = _now() + timeout_s
    last_err: Optional[Exception] = None
    while _now() < deadline:
        try:
            if not ARTIFACTS_ROOT.exists():
                time.sleep(0.1)
                continue
            candidates: List[Tuple[float, Path]] = []
            for d in ARTIFACTS_ROOT.iterdir():
                if not d.is_dir():
                    continue
                status = d / "status.json"
                events = d / "events.jsonl"
                if status.exists() and events.exists():
                    m = max(status.stat().st_mtime, events.stat().st_mtime)
                    candidates.append((m, d))
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                run_dir = candidates[0][1]
                return RunArtifacts(
                    run_dir=run_dir,
                    events_jsonl=run_dir / "events.jsonl",
                    status_json=run_dir / "status.json",
                    page_source_xml=run_dir / "page_source.xml",
                    screenshot_png=run_dir / "screenshot.png",
                )
        except Exception as e:
            last_err = e
        time.sleep(0.1)
    if last_err:
        raise last_err
    raise TimeoutError("未找到任何 artifacts/<run_id>/{events.jsonl,status.json}")


def discover_healthy_run_artifacts(*, freshness_s: float) -> Optional[RunArtifacts]:
    if not is_managed_process_running():
        return None
    try:
        run = discover_latest_run_artifacts(timeout_s=0.2)
    except Exception:
        return None
    newest = max(_file_mtime(run.status_json), _file_mtime(run.events_jsonl))
    if newest <= 0 or (_now() - newest) > freshness_s:
        return None
    try:
        status = _read_json(run.status_json)
    except Exception:
        return None
    if status.get("run_id") and status.get("run_id") != run.run_dir.name:
        return None
    return run


def wait_command_ready(status_json: Path, *, timeout_s: float) -> Dict[str, Any]:
    deadline = _now() + timeout_s
    last: Dict[str, Any] = {}
    while _now() < deadline:
        try:
            last = _read_json(status_json)
        except Exception:
            time.sleep(0.2)
            continue

        fg = last.get("foreground_app")
        anchors = set(last.get("anchors") or [])
        pipeline = last.get("pipeline") or {}
        lock_state = pipeline.get("ui_lock")
        if fg == "Soul" and "message_content" in anchors and lock_state == "unlocked":
            return last
        time.sleep(0.5)
    raise TimeoutError(f"等待 CommandReady 超时。最后 status={last}")


def inject(proc: subprocess.Popen[bytes], line: str) -> None:
    if proc.stdin is None:
        raise RuntimeError("子进程 stdin 不可用，无法注入命令")
    proc.stdin.write((line.rstrip("\n") + "\n").encode("utf-8"))
    proc.stdin.flush()


def inject_via_channel(proc: Optional[subprocess.Popen[bytes]], line: str) -> Tuple[str, Optional[Path]]:
    if proc is not None:
        inject(proc, line)
        return "stdin", None
    return "agent_spool", write_spool_command(line)


def choose_lifecycle(
    *,
    restart: str,
    freshness_s: float,
    stop_timeout_s: float,
) -> Tuple[Optional[subprocess.Popen[bytes]], Optional[RunArtifacts], bool, str]:
    """
    Decide whether to restart, reuse, or start the managed process.

    Kept as a small pure-ish seam so the runner's lifecycle policy is testable
    without launching Appium.
    """
    if restart == "always":
        stop_existing(timeout_s=stop_timeout_s)
        return start_service(), None, True, "restarted"
    if restart == "auto":
        healthy = discover_healthy_run_artifacts(freshness_s=freshness_s)
        if healthy is not None:
            return None, healthy, False, "reused"
        return start_service(), None, True, "started"
    return None, None, False, "reused"


def assert_command_flow(
    events_jsonl: Path,
    *,
    injected: str,
    timeout_s: float,
    start_offset: int = 0,
) -> Dict[str, Any]:
    """
    Wait until we see a minimal chain that proves the injected command was handled.
    """
    deadline = _now() + timeout_s
    offset = start_offset
    seen: Dict[str, Any] = {"events": []}
    want_content = injected.strip()
    have_enqueue = False
    have_result = False
    last_result: Optional[Dict[str, Any]] = None

    while _now() < deadline:
        if events_jsonl.exists():
            for offset, evt in _iter_jsonl(events_jsonl, offset=offset):
                e = evt.get("event")
                ctx = evt.get("ctx") or {}
                seen["events"].append(e)

                if e == "queue.enqueue" and (ctx.get("content") == want_content):
                    have_enqueue = True
                if e == "command.result":
                    # prefer matching prefix for the injected command if present
                    injected_prefix = want_content[1:].split()[0] if want_content[:1] in (":", "：") else None
                    if injected_prefix is None or (ctx.get("prefix") == injected_prefix):
                        have_result = True
                        last_result = evt

            if have_enqueue and have_result and last_result is not None:
                return {
                    "ok": True,
                    "last_command_result": last_result,
                    "observed_events": seen["events"][-50:],
                }
        time.sleep(0.2)

    return {"ok": False, "observed_events": seen["events"][-200:], "last_command_result": last_result}


def find_log_files() -> List[Path]:
    roots = [REPO_ROOT / "logs"]
    out: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.log"):
            if path.is_file():
                out.append(path)
    out.sort(key=lambda p: _file_mtime(p), reverse=True)
    return out


def tail_text(path: Path, *, max_bytes: int = 65536) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"LOG_READ_ERROR: {e}"


def run_log_assertions(
    patterns: List[str],
    *,
    log_file: Optional[Path],
) -> List[Dict[str, Any]]:
    if not patterns:
        return []
    files = [log_file] if log_file else find_log_files()[:5]
    files = [p for p in files if p is not None]
    checks: List[Dict[str, Any]] = []
    for pattern in patterns:
        compiled: Optional[Pattern[str]]
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            checks.append({"pattern": pattern, "ok": False, "error": f"invalid regex: {e}", "files": []})
            continue
        matched_file: Optional[str] = None
        excerpt = ""
        for path in files:
            text = tail_text(path)
            match = compiled.search(text)
            if match:
                matched_file = str(path)
                start = max(0, match.start() - 240)
                end = min(len(text), match.end() + 240)
                excerpt = text[start:end]
                break
        checks.append({"pattern": pattern, "ok": bool(matched_file), "file": matched_file, "excerpt": excerpt})
    return checks


def run_ui_assertions(
    run: RunArtifacts,
    *,
    page_source_texts: List[str],
    require_screenshot: bool,
) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    if page_source_texts:
        text = run.page_source_xml.read_text(encoding="utf-8", errors="replace") if run.page_source_xml.exists() else ""
        for expected in page_source_texts:
            checks.append(
                {
                    "type": "page_source_contains",
                    "expected": expected,
                    "path": str(run.page_source_xml),
                    "ok": expected in text,
                }
            )
    if require_screenshot:
        checks.append(
            {
                "type": "screenshot_exists",
                "path": str(run.screenshot_png),
                "ok": run.screenshot_png.exists() and run.screenshot_png.stat().st_size > 0,
            }
        )
    return checks


def summarize_checks(checks: List[Dict[str, Any]]) -> bool:
    return all(bool(c.get("ok")) for c in checks)


def write_report(
    run_dir: Path,
    *,
    title: str,
    trigger: str,
    trigger_reason: str,
    scenario: str,
    lifecycle_action: str,
    injection_channel: str,
    blocker: str,
    injected: str,
    status: Optional[Dict[str, Any]],
    assertion: Dict[str, Any],
    db_checks: List[Tuple[str, List[Tuple[Any, ...]]]],
    log_checks: List[Dict[str, Any]],
    ui_checks: List[Dict[str, Any]],
) -> Path:
    p = run_dir / "agent_e2e_report.md"
    lines: List[str] = []
    lines.append(f"## {title}")
    lines.append("")
    lines.append(f"- **injected**: `{injected}`")
    lines.append(f"- **ok**: `{assertion.get('ok')}`")
    lines.append(f"- **trigger**: `{trigger}`")
    if trigger_reason:
        lines.append(f"- **trigger_reason**: {trigger_reason}")
    lines.append(f"- **scenario**: `{scenario}`")
    lines.append(f"- **lifecycle_action**: `{lifecycle_action}`")
    lines.append(f"- **injection_channel**: `{injection_channel}`")
    if blocker:
        lines.append(f"- **blocker**: {blocker}")
    lines.append("")
    lines.append("### Evidence")
    lines.append(f"- `events.jsonl`: `{(run_dir / 'events.jsonl').as_posix()}`")
    lines.append(f"- `status.json`: `{(run_dir / 'status.json').as_posix()}`")
    lines.append(f"- `page_source.xml`: `{(run_dir / 'page_source.xml').as_posix()}`")
    lines.append(f"- `screenshot.png`: `{(run_dir / 'screenshot.png').as_posix()}`")
    lines.append("")
    if status is not None:
        lines.append("### Last status snapshot (trimmed)")
        fg = status.get("foreground_app")
        anchors = status.get("anchors")
        pipeline = status.get("pipeline")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps({"foreground_app": fg, "anchors": anchors, "pipeline": pipeline}, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    lines.append("### Assertion summary")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(assertion, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    if db_checks:
        lines.append("### DB checks")
        lines.append("")
        for q, rows in db_checks:
            lines.append(f"- **query**: `{q}`")
            lines.append("")
            lines.append("```")
            for r in rows[:50]:
                lines.append(str(r))
            lines.append("```")
            lines.append("")
    if log_checks:
        lines.append("### Log checks")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(log_checks, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    if ui_checks:
        lines.append("### UI evidence checks")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(ui_checks, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    p.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return p


def run_db_queries(db_path: Path, queries: List[str]) -> List[Tuple[str, List[Tuple[Any, ...]]]]:
    if not queries:
        return []
    if not db_path.exists():
        return [(q, [("DB_NOT_FOUND", str(db_path))]) for q in queries]
    out: List[Tuple[str, List[Tuple[Any, ...]]]] = []
    conn = sqlite3.connect(str(db_path))
    try:
        for q in queries:
            try:
                rows = list(conn.execute(q).fetchall())
            except Exception as e:
                rows = [("ERROR", str(e))]
            out.append((q, rows))
    finally:
        conn.close()
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Agent-friendly E2E runner for UShareIPlay (closed loop).")
    parser.add_argument("--command", default="", help="Injected console command, e.g. ':help'. If empty, will prompt in TTY.")
    parser.add_argument("--startup-timeout", type=float, default=120.0, help="Seconds to wait artifacts appear")
    parser.add_argument("--ready-timeout", type=float, default=180.0, help="Seconds to wait CommandReady")
    parser.add_argument("--assert-timeout", type=float, default=90.0, help="Seconds to wait command result events")
    parser.add_argument("--stop-timeout", type=float, default=8.0, help="Seconds to stop existing process")
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "soul_bot.db"), help="SQLite DB path for read-only checks")
    parser.add_argument("--db-query", action="append", default=[], help="SQLite SELECT query to run after assertion (repeatable)")
    parser.add_argument("--expect-log-regex", action="append", default=[], help="Regex expected in recent logs (repeatable)")
    parser.add_argument("--log-file", default="", help="Specific log file for --expect-log-regex")
    parser.add_argument("--expect-page-source-text", action="append", default=[], help="Text expected in page_source.xml (repeatable)")
    parser.add_argument("--require-screenshot", action="store_true", help="Require screenshot.png to exist and be non-empty")
    parser.add_argument("--dump-after-command", action="store_true", help="Request !dump after command before UI evidence checks")
    parser.add_argument("--dump-on-fail", action="store_true", help="If assertion fails, inject '!dump' to collect artifacts")
    parser.add_argument("--keep-running", action="store_true", help="Do not terminate the started process")
    parser.add_argument("--mode", choices=["full", "smoke"], default="full", help="smoke: no process start/stop; only parse latest artifacts")
    parser.add_argument("--trigger", choices=["auto", "manual"], default="manual", help="Why E2E was triggered")
    parser.add_argument("--trigger-reason", default="", help="Short reason or user request for the E2E run")
    parser.add_argument("--health-freshness", type=float, default=30.0, help="Seconds artifacts may be old and still count as healthy")
    parser.add_argument(
        "--scenario",
        choices=["auto", "dev", "test"],
        default="auto",
        help="auto: infer based on repo changes. dev: restart always. test: reuse if possible.",
    )
    parser.add_argument(
        "--restart",
        choices=["auto", "always", "never"],
        default="auto",
        help="auto: reuse managed process if running, else start. always: stop then start. never: never stop/start (requires existing artifacts).",
    )
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)
    _ensure_agent_dir()

    inferred_scenario = args.scenario
    if inferred_scenario == "auto":
        inferred_scenario = "dev" if git_has_uncommitted_changes() else "test"
    if args.restart == "auto":
        args.restart = "always" if inferred_scenario == "dev" else "auto"

    if not args.command:
        args.command = _prompt("请输入要测试的 console 命令（例如 :help ）> ")
    if not args.command.startswith((":", "：", "!", "！")):
        raise RuntimeError(f"command 必须以 ':' 或 '!' 开头，当前为：{args.command!r}")

    started_after = _now()
    proc: Optional[subprocess.Popen[bytes]] = None
    run: Optional[RunArtifacts] = None
    last_status: Optional[Dict[str, Any]] = None
    assertion: Dict[str, Any] = {"ok": False}
    log_checks: List[Dict[str, Any]] = []
    ui_checks: List[Dict[str, Any]] = []
    blocker = ""
    lifecycle_action = "none"
    injection_channel = "none"

    started_by_runner = False

    if args.mode == "full":
        proc, run, started_by_runner, lifecycle_action = choose_lifecycle(
            restart=args.restart,
            freshness_s=args.health_freshness,
            stop_timeout_s=args.stop_timeout,
        )
    else:
        # smoke mode will self-generate artifacts; no service start/stop.
        lifecycle_action = "smoke"
        pass

    try:
        if args.mode == "smoke":
            from ushareiplay.core.observability import Observability, new_run_id

            rid = new_run_id()
            obs = Observability(run_id=rid)
            obs.emit("app.start", ctx={"component": "agent_e2e_smoke"})
            obs.write_status(
                {
                    "foreground_app": "Soul",
                    "anchors": ["message_content"],
                    "pipeline": {"ui_lock": "unlocked", "queue_size": 0},
                }
            )
            p = obs.paths()
            run = RunArtifacts(
                run_dir=p.run_dir,
                events_jsonl=p.events_jsonl,
                status_json=p.status_json,
                page_source_xml=p.page_source_xml,
                screenshot_png=p.screenshot_png,
            )
            last_status = _read_json(run.status_json)
            assertion = {"ok": True, "note": "smoke mode: generated artifacts via Observability"}
        else:
            if args.restart == "never" and not ARTIFACTS_ROOT.exists():
                raise RuntimeError("--restart never 但当前没有 artifacts 可用于断言。")
            if run is None and started_by_runner:
                run = discover_run_artifacts(started_after=started_after, timeout_s=args.startup_timeout)
            elif run is None:
                run = discover_latest_run_artifacts(timeout_s=2.0)

        if args.mode == "full" and run is not None:
            last_status = wait_command_ready(run.status_json, timeout_s=args.ready_timeout)
            event_offset = run.events_jsonl.stat().st_size if run.events_jsonl.exists() else 0
            injection_channel, _spool_path = inject_via_channel(proc, args.command)
            assertion = assert_command_flow(
                run.events_jsonl,
                injected=args.command,
                timeout_s=args.assert_timeout,
                start_offset=event_offset,
            )
            needs_dump = args.dump_after_command or bool(args.expect_page_source_text) or args.require_screenshot
            if needs_dump:
                inject_via_channel(proc, "!dump")
                time.sleep(1.0)
            if (not assertion.get("ok")) and args.dump_on_fail:
                inject_via_channel(proc, "!dump")
                # give it a little time to flush to disk
                time.sleep(1.0)

        db_checks = run_db_queries(Path(args.db), list(args.db_query))
        log_checks = run_log_assertions(
            list(args.expect_log_regex),
            log_file=Path(args.log_file) if args.log_file else None,
        )
        ui_checks = run_ui_assertions(
            run,
            page_source_texts=list(args.expect_page_source_text),
            require_screenshot=bool(args.require_screenshot),
        )
        db_ok = all(not rows or rows[0][0] not in ("ERROR", "DB_NOT_FOUND") for _, rows in db_checks)
        evidence_ok = db_ok and summarize_checks(log_checks) and summarize_checks(ui_checks)
        assertion = dict(assertion)
        assertion["log_ok"] = summarize_checks(log_checks)
        assertion["ui_ok"] = summarize_checks(ui_checks)
        assertion["db_ok"] = db_ok
        assertion["ok"] = bool(assertion.get("ok")) and evidence_ok
        report = write_report(
            run.run_dir,
            title="agent-e2e-observability closed-loop report",
            trigger=args.trigger,
            trigger_reason=args.trigger_reason,
            scenario=inferred_scenario,
            lifecycle_action=lifecycle_action,
            injection_channel=injection_channel,
            blocker=blocker,
            injected=args.command,
            status=last_status,
            assertion=assertion,
            db_checks=db_checks,
            log_checks=log_checks,
            ui_checks=ui_checks,
        )
        print(report.as_posix())
        return 0 if assertion.get("ok") else 2

    finally:
        if args.mode == "full" and started_by_runner and proc is not None and (not args.keep_running):
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                pass
            try:
                proc.wait(timeout=6)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
