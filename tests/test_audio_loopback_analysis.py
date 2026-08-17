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


def _dual_tone(sample_rate=8000, seconds=5.0):
    time = np.arange(int(sample_rate * seconds)) / sample_rate
    return 0.45 * np.sin(2 * np.pi * 440 * time) + 0.10 * np.sin(2 * np.pi * 997 * time)


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


def test_measurement_accepts_phase_shifted_dual_tone_after_mobile_audio_processing():
    analyzer = _load_analyzer()
    source = _dual_tone()
    time = np.arange(len(source)) / 8000
    captured = 0.7 * (0.45 * np.sin(2 * np.pi * 440 * time + 0.8) + 0.10 * np.sin(2 * np.pi * 997 * time + 0.3))

    result = analyzer.measure(source, captured, sample_rate=8000)

    assert result.passed is True
    assert result.correlation < analyzer.MIN_CORRELATION
    assert result.expected_frequencies_hz == (440.0, 997.0)
    assert result.active_tone_frames >= result.required_tone_frames
    assert result.tone_ratio_error is not None and result.tone_ratio_error < analyzer.MAX_TONE_RATIO_ERROR


def test_measurement_rejects_capture_missing_a_required_tone():
    analyzer = _load_analyzer()
    source = _dual_tone()
    captured = _sine(seconds=5.0)

    result = analyzer.measure(source, captured, sample_rate=8000)

    assert result.passed is False
    assert "tone_fingerprint" in result.failures
