"""Shared coordination primitives for the UShareIPlay E2E toolbelt."""

from __future__ import annotations

import base64
import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


LEASE_ROOT = Path.home() / ".ushareiplay" / "device-leases"
LEASE_TTL_S = 30 * 60


@dataclass(frozen=True)
class RemoteTarget:
    host: str
    deploy_path: str


class LeaseConflict(RuntimeError):
    def __init__(self, lease: dict[str, Any]):
        self.lease = lease
        super().__init__(f"device lease is held by pid {lease.get('owner_pid')}")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def lease_path(device_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in device_id)
    return LEASE_ROOT / f"{safe}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _lease_is_live(lease: dict[str, Any]) -> bool:
    heartbeat = float(lease.get("heartbeat_at", 0))
    owner_pid = int(lease.get("owner_pid", lease.get("pid", 0)) or 0)
    return heartbeat >= time.time() - LEASE_TTL_S and owner_pid > 0 and pid_alive(owner_pid)


def acquire_lease(device_id: str, *, session_id: str, worktree: str) -> dict[str, Any]:
    """Acquire a user-wide device lease, reclaiming only dead or expired owners."""
    path = lease_path(device_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = _read_json(path)
    if previous and _lease_is_live(previous):
        raise LeaseConflict(previous)
    if previous:
        path.unlink(missing_ok=True)

    now = time.time()
    lease = {
        "device_id": device_id,
        "session_id": session_id,
        "owner_pid": os.getpid(),
        "worktree": worktree,
        "created_at": now,
        "heartbeat_at": now,
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        current = _read_json(path) or {"device_id": device_id}
        raise LeaseConflict(current) from None
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(lease, f, ensure_ascii=False)
    return lease


def release_lease(device_id: str, *, session_id: str) -> bool:
    path = lease_path(device_id)
    current = _read_json(path)
    if not current or current.get("session_id") != session_id:
        return False
    path.unlink(missing_ok=True)
    return True


def transfer_lease_owner(device_id: str, *, session_id: str, owner_pid: int) -> dict[str, Any]:
    """Bind a provisional CLI lease to the long-lived service process."""
    path = lease_path(device_id)
    current = _read_json(path)
    if not current or current.get("session_id") != session_id:
        raise LeaseConflict(current or {"device_id": device_id})
    current["owner_pid"] = owner_pid
    current["heartbeat_at"] = time.time()
    path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    return current


def load_remote_target(config_path: Path) -> RemoteTarget | None:
    if not config_path.exists():
        return None
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        remote = loaded.get("agent_e2e", {}).get("remote", {})
        host = remote.get("host")
        deploy_path = remote.get("deploy_path")
    except Exception as exc:
        raise ValueError(f"invalid remote configuration: {exc}") from exc
    if not host and not deploy_path:
        return None
    if not isinstance(host, str) or not isinstance(deploy_path, str) or not host or not deploy_path:
        raise ValueError("agent_e2e.remote requires non-empty host and deploy_path")
    return RemoteTarget(host=host, deploy_path=deploy_path)


def run_text(args: list[str], *, timeout: float = 10) -> str:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    return result.stdout


def process_cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def _process_matches(command: str, cwd: str | None, device_id: str) -> bool:
    text = f"{command} {cwd or ''}".lower()
    # The shared Android/Appium target permits only one UShareIPlay service per
    # machine. A manually started process often omits the device from argv, so
    # repository identity is the safe, useful discriminator here.
    return "ushareiplay" in text and ("main.py" in text or "run.sh" in text or "agent_e2e" in text or "e2e_toolbelt" in text)


def discover_local_sessions(device_id: str) -> list[dict[str, Any]]:
    """Find both managed and manually-started E2E process roots for one device."""
    output = run_text(["ps", "-axo", "pid=,pgid=,lstart=,command="], timeout=5)
    sessions: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.strip().split(None, 8)
        if len(parts) < 9 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        pid = int(parts[0])
        if pid in {os.getpid(), os.getppid()}:
            continue
        command = parts[8]
        cwd = process_cwd(pid)
        if _process_matches(command, cwd, device_id):
            sessions.append({
                "kind": "external/orphan",
                "pid": pid,
                "pgid": int(parts[1]),
                "started": " ".join(parts[2:7]),
                "command": command,
                "cwd": cwd,
            })
    return sessions


def terminate_sessions(sessions: list[dict[str, Any]], *, timeout_s: float, force: bool) -> list[dict[str, Any]]:
    """Stop distinct process groups and optionally escalate after the grace period."""
    groups = {int(item["pgid"]) for item in sessions if item.get("pgid")}
    for pgid in groups:
        try:
            os.killpg(pgid, signal.SIGINT)
        except OSError:
            pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        alive = [item for item in sessions if pid_alive(int(item["pid"]))]
        if not alive:
            return []
        time.sleep(0.2)
    alive = [item for item in sessions if pid_alive(int(item["pid"]))]
    if force:
        for pgid in {int(item["pgid"]) for item in alive if item.get("pgid")}:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
    return [item for item in sessions if pid_alive(int(item["pid"]))]


def remote_command(target: RemoteTarget, action: str) -> list[str]:
    """Build a non-interactive SSH action without deployment-manager configuration."""
    root = (
        "$HOME/" + shlex.quote(target.deploy_path[2:])
        if target.deploy_path.startswith("~/")
        else shlex.quote(target.deploy_path)
    )
    find_pids = (
        "find_processes() { ps -eo pid=,ppid=,pgid=,args= | awk -v root=\"$PWD\" -v self=\"$$\" "
        "'$1 != self && $2 != self && $4 != \"awk\" && (index($0, root) || /bash \\.\\/run\\.sh$/ || /uv run ushareiplay/) {print $1, $3}'; }; "
        "find_pids() { find_processes | awk '{print $1}'; }; "
        "find_pgids() { find_processes | awk '{print $2}' | sort -u; }"
    )
    if action == "status":
        script = f"set -eu; cd -- {root}; {find_pids}; printf 'cwd=%s\\n' \"$PWD\"; find_pids"
    elif action == "pause":
        script = f"set -eu; cd -- {root}; {find_pids}; pgids=$(find_pgids); for pgid in $pgids; do kill -INT -- -\"$pgid\" || true; done; for _ in {{1..8}}; do remaining=$(find_pids); test -z \"$remaining\" && exit 0; sleep 1; done; printf '%s\\n' \"$remaining\"; exit 3"
    elif action == "force-stop":
        script = f"set -eu; cd -- {root}; {find_pids}; for pid in $(find_pids); do kill -KILL \"$pid\" || true; done"
    elif action == "resume":
        script = (
            f"set -eu; cd -- {root}; mkdir -p .agent; "
            "if command -v uv >/dev/null 2>&1; then "
            "nohup bash ./run.sh > .agent/e2e-remote-resume.log 2>&1 & "
            "else test -x ./.venv/bin/ushareiplay; "
            "nohup ./.venv/bin/ushareiplay > .agent/e2e-remote-resume.log 2>&1 & fi; "
            "printf 'pid=%s\\n' \"$!\""
        )
    elif action == "logs":
        script = (
            f"set -eu; cd -- {root}; "
            "find logs artifacts .agent -type f \\( -name '*.log' -o -name 'events.jsonl' -o -name 'status.json' \\) -mmin -30 -print "
            "| while IFS= read -r file; do printf '==> %s\\n' \"$file\"; "
            "tail -c 65536 \"$file\" | sed -E 's/((token|password|secret|cookie|authorization)[=:])[[:graph:]]+/\\1REDACTED/Ig'; done"
        )
    else:
        raise ValueError(f"unknown remote action: {action}")
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target.host, f"echo {encoded} | base64 -d | bash"]
