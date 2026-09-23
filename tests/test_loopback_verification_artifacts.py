import importlib.util
import json
import sys
from pathlib import Path

import numpy as np


def _load_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "loopback_verification.py"
    spec = importlib.util.spec_from_file_location("loopback_verification", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_write_evidence_retains_pcm_hashes_and_invalid_negative_control(tmp_path):
    verifier = _load_verifier()
    time = np.arange(8000) / 8000
    source = (0.6 * np.sin(2 * np.pi * 440 * time)).astype(np.float64)

    report_path = verifier.write_evidence(tmp_path, source, source, source, sample_rate=8000)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["reason"] == "negative_control_passed"
    assert set(report["sha256"]) == {"source.pcm", "positive.pcm", "negative.pcm"}
    assert all((tmp_path / name).is_file() for name in report["sha256"])


def test_read_pcm_s16le_round_trips_audio_samples(tmp_path):
    verifier = _load_verifier()
    samples = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])
    path = tmp_path / "samples.pcm"
    verifier.write_pcm(path, samples)

    loaded = verifier.read_pcm(path)

    np.testing.assert_allclose(loaded, samples, atol=1 / 32767)
