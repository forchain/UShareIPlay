import json
from pathlib import Path

from ushareiplay.core.observability import Observability


class FakeDriver:
    page_source = "<hierarchy><node package='cn.soulapp.android' resource-id='cn.soulapp.android:id/rvMessage'/></hierarchy>"

    def get_screenshot_as_file(self, path: str) -> bool:
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
        return True


def test_observability_writes_events_and_status(tmp_path: Path, monkeypatch):
    # Force artifacts under temp directory by chdir-ing and creating minimal root layout.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("logging:\n  directory: logs\n", encoding="utf-8")
    (tmp_path / "src").mkdir()

    obs = Observability(run_id="test-run")
    obs.emit("app.start", ctx={"component": "test"})
    status_path = obs.write_status({"foreground_app": "Soul", "anchors": ["message_content"]})

    events_path = obs.paths().events_jsonl
    assert events_path.exists()
    assert status_path.exists()

    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    evt = json.loads(lines[0])
    assert evt["event"] == "app.start"
    assert evt["run_id"] == "test-run"

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["run_id"] == "test-run"
    assert status["foreground_app"] == "Soul"

