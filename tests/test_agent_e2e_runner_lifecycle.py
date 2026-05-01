import importlib.util
import os
import sys
from pathlib import Path


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "agent_e2e.py"
    spec = importlib.util.spec_from_file_location("agent_e2e_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeProc:
    stdin = None


def _write_run(root: Path, run_id: str = "run-1") -> Path:
    run = root / run_id
    run.mkdir(parents=True)
    (run / "status.json").write_text(f'{{"run_id":"{run_id}"}}', encoding="utf-8")
    (run / "events.jsonl").write_text("", encoding="utf-8")
    return run


def test_discover_healthy_run_requires_live_pid_and_fresh_artifacts(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "ARTIFACTS_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(runner, "AGENT_DIR", tmp_path / ".agent")
    monkeypatch.setattr(runner, "PID_FILE", tmp_path / ".agent" / "ushareiplay.pid")
    monkeypatch.setattr(runner, "COMMAND_SPOOL_DIR", tmp_path / ".agent" / "commands")
    runner._ensure_agent_dir()
    runner.PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    _write_run(runner.ARTIFACTS_ROOT)

    healthy = runner.discover_healthy_run_artifacts(freshness_s=60)

    assert healthy is not None
    assert healthy.run_dir.name == "run-1"


def test_choose_lifecycle_dev_restart_stops_and_starts(monkeypatch):
    runner = _load_runner()
    calls = []
    monkeypatch.setattr(runner, "stop_existing", lambda timeout_s: calls.append(("stop", timeout_s)))
    monkeypatch.setattr(runner, "start_service", lambda: calls.append(("start", None)) or FakeProc())

    proc, run, started, action = runner.choose_lifecycle(
        restart="always",
        freshness_s=60,
        stop_timeout_s=3,
    )

    assert isinstance(proc, FakeProc)
    assert run is None
    assert started is True
    assert action == "restarted"
    assert calls == [("stop", 3), ("start", None)]


def test_choose_lifecycle_test_reuses_healthy_process(monkeypatch):
    runner = _load_runner()
    fake_run = object()
    monkeypatch.setattr(runner, "discover_healthy_run_artifacts", lambda freshness_s: fake_run)
    monkeypatch.setattr(runner, "start_service", lambda: (_ for _ in ()).throw(AssertionError("should not start")))

    proc, run, started, action = runner.choose_lifecycle(
        restart="auto",
        freshness_s=60,
        stop_timeout_s=3,
    )

    assert proc is None
    assert run is fake_run
    assert started is False
    assert action == "reused"


def test_choose_lifecycle_test_starts_when_no_healthy_process(monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "discover_healthy_run_artifacts", lambda freshness_s: None)
    monkeypatch.setattr(runner, "start_service", lambda: FakeProc())

    proc, run, started, action = runner.choose_lifecycle(
        restart="auto",
        freshness_s=60,
        stop_timeout_s=3,
    )

    assert isinstance(proc, FakeProc)
    assert run is None
    assert started is True
    assert action == "started"


def test_reused_process_injection_failure_is_explicit(monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "write_spool_command", lambda line: (_ for _ in ()).throw(RuntimeError("spool unavailable")))

    try:
        runner.inject_via_channel(None, ":help")
    except RuntimeError as exc:
        assert "spool unavailable" in str(exc)
    else:
        raise AssertionError("expected injection failure")
