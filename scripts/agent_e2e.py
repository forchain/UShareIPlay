#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
AGENT_DIR = REPO_ROOT / ".agent"
PID_FILE = AGENT_DIR / "ushareiplay.pid"


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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_existing(*, timeout_s: float = 8.0) -> None:
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        PID_FILE.unlink(missing_ok=True)
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

    # hard kill
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
    PID_FILE.unlink(missing_ok=True)


def read_managed_pid() -> Optional[int]:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    return pid


def is_managed_process_running() -> bool:
    pid = read_managed_pid()
    return bool(pid is not None and _pid_alive(pid))


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
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return proc


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


def assert_command_flow(
    events_jsonl: Path,
    *,
    injected: str,
    timeout_s: float,
) -> Dict[str, Any]:
    """
    Wait until we see a minimal chain that proves the injected command was handled.
    """
    deadline = _now() + timeout_s
    offset = 0
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


def write_report(
    run_dir: Path,
    *,
    title: str,
    injected: str,
    status: Optional[Dict[str, Any]],
    assertion: Dict[str, Any],
    db_checks: List[Tuple[str, List[Tuple[Any, ...]]]],
) -> Path:
    p = run_dir / "agent_e2e_report.md"
    lines: List[str] = []
    lines.append(f"## {title}")
    lines.append("")
    lines.append(f"- **injected**: `{injected}`")
    lines.append(f"- **ok**: `{assertion.get('ok')}`")
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
    parser.add_argument("--dump-on-fail", action="store_true", help="If assertion fails, inject '!dump' to collect artifacts")
    parser.add_argument("--keep-running", action="store_true", help="Do not terminate the started process")
    parser.add_argument("--mode", choices=["full", "smoke"], default="full", help="smoke: no process start/stop; only parse latest artifacts")
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

    started_by_runner = False

    if args.mode == "full":
        if args.restart == "always":
            stop_existing(timeout_s=args.stop_timeout)
            proc = start_service()
            started_by_runner = True
        elif args.restart == "auto":
            if is_managed_process_running():
                proc = None
            else:
                proc = start_service()
                started_by_runner = True
        else:  # never
            proc = None
    else:
        # smoke mode will self-generate artifacts; no service start/stop.
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
            if started_by_runner:
                run = discover_run_artifacts(started_after=started_after, timeout_s=args.startup_timeout)
            else:
                run = discover_latest_run_artifacts(timeout_s=2.0)

        if args.mode == "full" and run is not None:
            last_status = wait_command_ready(run.status_json, timeout_s=args.ready_timeout)
            if proc is None:
                raise RuntimeError("当前选择复用已有进程，但没有可注入的 stdin。请使用 --restart always/auto 由 Runner 启动，或保持 keep-running 并自行注入。")
            inject(proc, args.command)
            assertion = assert_command_flow(run.events_jsonl, injected=args.command, timeout_s=args.assert_timeout)
            if (not assertion.get("ok")) and args.dump_on_fail:
                inject(proc, "!dump")
                # give it a little time to flush to disk
                time.sleep(1.0)

        db_checks = run_db_queries(Path(args.db), list(args.db_query))
        report = write_report(
            run.run_dir,
            title="agent-e2e-observability closed-loop report",
            injected=args.command,
            status=last_status,
            assertion=assertion,
            db_checks=db_checks,
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

