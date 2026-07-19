import importlib.util
import json
import os
import sys
import time
import base64
from pathlib import Path


def _load_coordination():
    path = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "agent-e2e-test" / "scripts" / "e2e_coordination.py"
    spec = importlib.util.spec_from_file_location("agent_e2e_coordination", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _remote_script(command):
    payload = command[-1].split()[1]
    return base64.b64decode(payload).decode("utf-8")


def test_load_remote_target_requires_only_host_and_deploy_path(tmp_path):
    coordination = _load_coordination()
    config = tmp_path / "config.local.yaml"
    config.write_text(
        "agent_e2e:\n  remote:\n    host: tony@192.168.8.103\n    deploy_path: ~/github.com/forchain/UShareIPlay\n",
        encoding="utf-8",
    )

    target = coordination.load_remote_target(config)

    assert target.host == "tony@192.168.8.103"
    assert target.deploy_path == "~/github.com/forchain/UShareIPlay"


def test_device_lease_reclaims_expired_dead_owner(tmp_path, monkeypatch):
    coordination = _load_coordination()
    monkeypatch.setattr(coordination, "LEASE_ROOT", tmp_path / "leases")
    lease_path = coordination.lease_path("device-1")
    lease_path.parent.mkdir(parents=True)
    lease_path.write_text(json.dumps({"device_id": "device-1", "pid": 999999, "heartbeat_at": 0}), encoding="utf-8")
    monkeypatch.setattr(coordination, "pid_alive", lambda pid: False)

    lease = coordination.acquire_lease("device-1", session_id="session-1", worktree="/tmp/worktree")

    assert lease["session_id"] == "session-1"
    assert json.loads(lease_path.read_text(encoding="utf-8"))["owner_pid"] == os.getpid()


def test_device_lease_rejects_live_owner(tmp_path, monkeypatch):
    coordination = _load_coordination()
    monkeypatch.setattr(coordination, "LEASE_ROOT", tmp_path / "leases")
    lease_path = coordination.lease_path("device-1")
    lease_path.parent.mkdir(parents=True)
    lease_path.write_text(json.dumps({"device_id": "device-1", "owner_pid": 1234, "heartbeat_at": time.time()}), encoding="utf-8")
    monkeypatch.setattr(coordination, "pid_alive", lambda pid: pid == 1234)

    try:
        coordination.acquire_lease("device-1", session_id="session-2", worktree="/tmp/worktree")
    except coordination.LeaseConflict as exc:
        assert exc.lease["owner_pid"] == 1234
    else:
        raise AssertionError("expected live lease to block acquisition")


def test_device_lease_transfers_ownership_to_the_service_pid(tmp_path, monkeypatch):
    coordination = _load_coordination()
    monkeypatch.setattr(coordination, "LEASE_ROOT", tmp_path / "leases")
    lease = coordination.acquire_lease("device-1", session_id="session-1", worktree="/tmp/worktree")

    updated = coordination.transfer_lease_owner("device-1", session_id="session-1", owner_pid=4321)

    assert updated["owner_pid"] == 4321
    assert json.loads(coordination.lease_path("device-1").read_text(encoding="utf-8"))["owner_pid"] == 4321


def test_process_inventory_marks_manual_repo_process_as_external_session(monkeypatch):
    coordination = _load_coordination()
    output = "123 123 Mon Jan  1 00:00:00 2026 python /tmp/UShareIPlay/main.py --device emulator-1\n"
    monkeypatch.setattr(coordination, "run_text", lambda *args, **kwargs: output)
    monkeypatch.setattr(coordination, "process_cwd", lambda pid: "/tmp/UShareIPlay")

    sessions = coordination.discover_local_sessions("emulator-1")

    assert len(sessions) == 1
    assert sessions[0]["kind"] == "external/orphan"
    assert sessions[0]["pid"] == 123


def test_remote_pause_command_is_graceful_and_force_is_explicit():
    coordination = _load_coordination()
    target = coordination.RemoteTarget(host="tony@192.168.8.103", deploy_path="~/github.com/forchain/UShareIPlay")

    graceful = coordination.remote_command(target, "pause")
    force = coordination.remote_command(target, "force-stop")

    assert "kill -INT" in _remote_script(graceful)
    assert "kill -KILL" not in _remote_script(graceful)
    assert "kill -KILL" in _remote_script(force)


def test_remote_resume_uses_the_deployment_run_script():
    coordination = _load_coordination()
    target = coordination.RemoteTarget(host="tony@192.168.8.103", deploy_path="~/github.com/forchain/UShareIPlay")

    command = coordination.remote_command(target, "resume")

    assert "nohup bash ./run.sh" in _remote_script(command)


def test_remote_resume_falls_back_to_the_project_virtualenv():
    coordination = _load_coordination()
    target = coordination.RemoteTarget(host="tony@192.168.8.103", deploy_path="~/github.com/forchain/UShareIPlay")

    command = coordination.remote_command(target, "resume")

    assert "./.venv/bin/ushareiplay" in _remote_script(command)


def test_remote_command_expands_a_home_relative_deploy_path():
    coordination = _load_coordination()
    target = coordination.RemoteTarget(host="tony@192.168.8.103", deploy_path="~/github.com/forchain/UShareIPlay")

    command = coordination.remote_command(target, "status")

    assert "$HOME/github.com/forchain/UShareIPlay" in _remote_script(command)


def test_remote_pause_runs_under_bash_and_excludes_its_own_pid():
    coordination = _load_coordination()
    target = coordination.RemoteTarget(host="tony@192.168.8.103", deploy_path="~/github.com/forchain/UShareIPlay")

    command = coordination.remote_command(target, "pause")

    assert command[-1].endswith("| base64 -d | bash")
    script = _remote_script(command)
    assert "-v self=" in script
    assert "$1 != self" in script
    assert "$2 != self" in script
    assert "$4 != \"awk\"" in script
    assert "find_pgids" in script
    assert "kill -INT -- -" in script
    assert "/bash \\.\\/run\\.sh$/" in script
