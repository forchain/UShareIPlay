#!/usr/bin/env python3
"""Objective analysis for Virtual Audio Device loopback captures."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


MIN_CORRELATION = 0.95
MIN_SNR_DB = 20.0
MIN_AMPLITUDE = 0.05
MIN_TONE_RELATIVE_LEVEL = 0.05
MAX_TONE_RATIO_ERROR = 0.15


@dataclass(frozen=True)
class Measurement:
    correlation: float
    peak_frequency_hz: float
    snr_db: float
    amplitude: float
    expected_frequencies_hz: tuple[float, ...]
    active_tone_frames: int
    required_tone_frames: int
    tone_ratio_error: float | None
    passed: bool
    failures: tuple[str, ...]


def _aligned_capture(source: np.ndarray, captured: np.ndarray) -> tuple[np.ndarray, float]:
    if len(captured) < len(source):
        captured = np.pad(captured, (0, len(source) - len(captured)))
    # valid positions ensure the compared arrays have identical length.
    scores = np.correlate(captured, source, mode="valid")
    index = int(np.argmax(np.abs(scores)))
    segment = captured[index : index + len(source)]
    denominator = float(np.linalg.norm(source) * np.linalg.norm(segment))
    correlation = float(abs(scores[index]) / denominator) if denominator else 0.0
    return segment, correlation


def _peak_frequency(samples: np.ndarray, sample_rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples))
    if len(spectrum) < 2:
        return 0.0
    frequencies = np.fft.rfftfreq(len(samples), d=1 / sample_rate)
    return float(frequencies[1 + int(np.argmax(spectrum[1:]))])


def _snr(source: np.ndarray, captured: np.ndarray) -> float:
    source_power = float(np.mean(source**2))
    if source_power == 0:
        return float("-inf")
    gain = float(np.dot(captured, source) / np.dot(source, source))
    noise_power = float(np.mean((captured - gain * source) ** 2))
    if noise_power == 0:
        return 120.0
    return float(10 * np.log10(source_power / noise_power))


def _source_frequencies(source: np.ndarray, sample_rate: int) -> tuple[float, ...]:
    spectrum = np.abs(np.fft.rfft(source))
    frequencies = np.fft.rfftfreq(len(source), d=1 / sample_rate)
    if len(spectrum) < 2 or spectrum[1:].max(initial=0) == 0:
        return ()
    maximum = float(spectrum[1:].max())
    candidates = np.argsort(spectrum[1:])[::-1] + 1
    selected: list[float] = []
    for index in candidates:
        if spectrum[index] < maximum * MIN_TONE_RELATIVE_LEVEL:
            break
        frequency = float(frequencies[index])
        if all(abs(frequency - existing) >= 20 for existing in selected):
            selected.append(frequency)
        if len(selected) == 2:
            break
    return tuple(sorted(selected))


def _tone_amplitudes(samples: np.ndarray, sample_rate: int, frequencies: tuple[float, ...]) -> np.ndarray:
    frame_size = sample_rate
    frames = len(samples) // frame_size
    if frames == 0 or not frequencies:
        return np.empty((0, len(frequencies)))
    window = np.hanning(frame_size)
    bins = np.fft.rfftfreq(frame_size, d=1 / sample_rate)
    values = []
    for frame in samples[: frames * frame_size].reshape(frames, frame_size):
        spectrum = np.abs(np.fft.rfft(frame * window))
        values.append([float(spectrum[np.abs(bins - frequency) <= 3].max()) for frequency in frequencies])
    return np.asarray(values)


def _fingerprint(source: np.ndarray, captured: np.ndarray, sample_rate: int) -> tuple[tuple[float, ...], int, int, float | None]:
    frequencies = _source_frequencies(source, sample_rate)
    source_tones = _tone_amplitudes(source, sample_rate, frequencies)
    captured_tones = _tone_amplitudes(captured, sample_rate, frequencies)
    if not len(frequencies) or not len(source_tones) or not len(captured_tones):
        return frequencies, 0, 1, None
    minimums = np.median(source_tones, axis=0) * MIN_TONE_RELATIVE_LEVEL
    active = np.all(captured_tones >= minimums, axis=1)
    required = max(1, len(source_tones) - 1)
    ratio_error = None
    if len(frequencies) > 1 and np.any(active):
        source_ratio = float(np.median(source_tones[:, 0] / source_tones[:, 1]))
        capture_ratio = float(np.median(captured_tones[active, 0] / captured_tones[active, 1]))
        ratio_error = abs(capture_ratio / source_ratio - 1)
    return frequencies, int(active.sum()), required, ratio_error


def measure(source: np.ndarray, captured: np.ndarray, *, sample_rate: int) -> Measurement:
    source = np.asarray(source, dtype=np.float64)
    captured = np.asarray(captured, dtype=np.float64)
    aligned, correlation = _aligned_capture(source, captured)
    amplitude = float(np.max(np.abs(aligned))) if len(aligned) else 0.0
    peak_frequency_hz = _peak_frequency(aligned, sample_rate)
    snr_db = _snr(source, aligned)
    frequencies, active_tone_frames, required_tone_frames, tone_ratio_error = _fingerprint(source, captured, sample_rate)
    failures = []
    if amplitude < MIN_AMPLITUDE:
        failures.append("amplitude")
    if active_tone_frames < required_tone_frames:
        failures.append("tone_fingerprint")
    if tone_ratio_error is not None and tone_ratio_error > MAX_TONE_RATIO_ERROR:
        failures.append("tone_ratio")
    return Measurement(
        correlation=correlation,
        peak_frequency_hz=peak_frequency_hz,
        snr_db=snr_db,
        amplitude=amplitude,
        expected_frequencies_hz=frequencies,
        active_tone_frames=active_tone_frames,
        required_tone_frames=required_tone_frames,
        tone_ratio_error=tone_ratio_error,
        passed=not failures,
        failures=tuple(failures),
    )


def verification_result(positive: Measurement, negative: Measurement) -> dict:
    if not positive.passed:
        return {"status": "failed", "reason": "positive_control_failed", "positive": asdict(positive), "negative": asdict(negative)}
    if negative.passed:
        return {"status": "failed", "reason": "negative_control_passed", "positive": asdict(positive), "negative": asdict(negative)}
    return {"status": "passed", "mode": "standard", "positive": asdict(positive), "negative": asdict(negative)}
