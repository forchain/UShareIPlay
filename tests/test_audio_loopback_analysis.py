import importlib.util
import sys
from pathlib import Path

import numpy as np


def _load_analyzer():
    path = Path(__file__).resolve().parents[1] / "scripts" / "audio_loopback_analysis.py"
    spec = importlib.util.spec_from_file_location("audio_loopback_analysis", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sine(frequency=440.0, sample_rate=8000, seconds=1.0):
    time = np.arange(int(sample_rate * seconds)) / sample_rate
    return 0.6 * np.sin(2 * np.pi * frequency * time)


def test_measurement_accepts_delayed_clean_reference_signal():
    analyzer = _load_analyzer()
    source = _sine()
    captured = np.concatenate((np.zeros(320), source))

    result = analyzer.measure(source, captured, sample_rate=8000)

    assert result.passed is True
    assert result.peak_frequency_hz == 440.0
    assert result.correlation >= 0.95
    assert result.snr_db >= 20.0


def test_measurement_rejects_silence():
    analyzer = _load_analyzer()
    source = _sine()

    result = analyzer.measure(source, np.zeros_like(source), sample_rate=8000)

    assert result.passed is False
    assert "amplitude" in result.failures


def test_verification_rejects_a_negative_control_that_also_passes():
    analyzer = _load_analyzer()
    source = _sine()
    positive = analyzer.measure(source, source, sample_rate=8000)
    negative = analyzer.measure(source, source, sample_rate=8000)

    result = analyzer.verification_result(positive, negative)

    assert result["status"] == "failed"
    assert result["reason"] == "negative_control_passed"
