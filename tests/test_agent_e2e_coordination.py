import importlib.util
import json
import os
import subprocess
import sys
import time
import base64
from pathlib import Path

import pytest


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


def _fake_bin(tmp_path: Path, *, ps_lines: list[str], with_uv: bool) -> Path:
    """Install a fake ``ps`` so process discovery is deterministic."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/usr/bin/env bash\ncat <<'PS_EOF'\n" + "\n".join(ps_lines) + "\nPS_EOF\n",
        encoding="utf-8",
    )
    ps.chmod(0o755)
    if with_uv:
        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)
    return bin_dir


def _run_resume_script(tmp_path: Path, *, ps_lines: list[str], with_uv: bool = False):
    """Execute the generated ``resume`` script inside a throwaway deployment directory.

    The fake ``ps`` decides whether a UShareIPlay process is alive; the sandbox
    ``run.sh`` leaves a marker file, so a second service can be detected from the
    filesystem instead of from the script's text.
    """
    coordination = _load_coordination()
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "run.sh").write_text(
        "#!/usr/bin/env bash\nprintf 'started\\n' >> .agent/started.marker\n",
        encoding="utf-8",
    )
    bin_dir = _fake_bin(tmp_path, ps_lines=ps_lines, with_uv=with_uv)

    target = coordination.RemoteTarget(host="tony@192.168.8.103", deploy_path=str(deploy))
    script = _remote_script(coordination.remote_command(target, "resume"))

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )
    return result, deploy


def _wait_for(path: Path, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


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


def test_discovery_never_returns_the_caller_process_group(monkeypatch):
    """调用方自己不能被当成待清理的 E2E 会话根。

    toolbelt 的命令行里同时带着仓库路径（ushareiplay）和脚本名（e2e_toolbelt），
    按"仓库身份"匹配时先把自己匹配进来，terminate_sessions 再 killpg 就是自杀：
    start/cleanup-local 拿到 130，整条 E2E 生命周期原地中断。托管服务一律以
    start_new_session 独立成组，所以排除本进程组不会漏掉真正的服务根。
    """
    import os

    coordination = _load_coordination()
    own_pgid = os.getpgid(0)
    other_pgid = own_pgid + 987654
    output = (
        f"{own_pgid + 7} {own_pgid} Mon Jan  1 00:00:00 2026 "
        f"python /tmp/UShareIPlay/.agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py start\n"
        f"{other_pgid + 9} {other_pgid} Mon Jan  1 00:00:00 2026 "
        f"python /tmp/UShareIPlay/.agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py start\n"
    )
    monkeypatch.setattr(coordination, "run_text", lambda *args, **kwargs: output)
    monkeypatch.setattr(coordination, "process_cwd", lambda pid: "/tmp/UShareIPlay")

    sessions = coordination.discover_local_sessions("emulator-1")

    assert [item["pid"] for item in sessions] == [other_pgid + 9]


def test_remote_pause_queues_stop_command_and_force_is_explicit():
    coordination = _load_coordination()
    target = coordination.RemoteTarget(host="tony@192.168.8.103", deploy_path="~/github.com/forchain/UShareIPlay")

    graceful = coordination.remote_command(target, "pause")
    force = coordination.remote_command(target, "force-stop")

    assert "!stop" in _remote_script(graceful)
    assert "commands" in _remote_script(graceful)
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


def test_remote_pause_uses_safe_bash_transport():
    coordination = _load_coordination()
    target = coordination.RemoteTarget(host="tony@192.168.8.103", deploy_path="~/github.com/forchain/UShareIPlay")

    command = coordination.remote_command(target, "pause")

    assert command[-1].endswith("| base64 -d | bash")
    script = _remote_script(command)
    assert "!stop" in script
    assert "commands" in script


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-only shell script")
def test_remote_resume_toggles_the_live_process_instead_of_starting_a_second_one(tmp_path):
    """A paused remote service is still alive: resume must toggle it, never spawn a twin.

    ``remote-pause`` queues ``!stop``, which only flips the runtime pause flag --
    the process keeps running. Spawning a new one would leave two services
    contending for the shared Android device.
    """
    result, deploy = _run_resume_script(tmp_path, ps_lines=["4242 4200 4200 bash ./run.sh"])

    assert result.returncode == 0, result.stdout + result.stderr
    queued = sorted((deploy / ".agent" / "commands").glob("*-remote-resume.cmd"))
    assert len(queued) == 1, result.stdout + result.stderr
    assert queued[0].read_text(encoding="utf-8") == "!stop\n"
    assert "resumed=existing" in result.stdout
    assert "4242" in result.stdout
    # The fallback branch must not have run: no second service, no resume log.
    assert not (deploy / ".agent" / "e2e-remote-resume.log").exists()
    assert not _wait_for(deploy / ".agent" / "started.marker", 1.0)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-only shell script")
def test_remote_resume_starts_a_new_process_when_nothing_is_alive(tmp_path):
    """Without a live service there is nothing to toggle, so resume starts one."""
    result, deploy = _run_resume_script(
        tmp_path,
        ps_lines=["4242 4200 4200 sshd: tony@pts/0"],
        with_uv=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert list((deploy / ".agent" / "commands").glob("*-remote-resume.cmd")) == []
    assert "pid=" in result.stdout
    assert _wait_for(deploy / ".agent" / "started.marker", 5.0)
