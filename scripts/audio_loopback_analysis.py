#!/usr/bin/env python3
"""Objective analysis for Virtual Audio Device loopback captures."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


MIN_CORRELATION = 0.95
MIN_SNR_DB = 20.0
MAX_FREQUENCY_ERROR_HZ = 2.0
MIN_AMPLITUDE = 0.05


@dataclass(frozen=True)
class Measurement:
    correlation: float
    peak_frequency_hz: float
    snr_db: float
    amplitude: float
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


def measure(source: np.ndarray, captured: np.ndarray, *, sample_rate: int, expected_frequency_hz: float = 440.0) -> Measurement:
    source = np.asarray(source, dtype=np.float64)
    captured = np.asarray(captured, dtype=np.float64)
    aligned, correlation = _aligned_capture(source, captured)
    amplitude = float(np.max(np.abs(aligned))) if len(aligned) else 0.0
    peak_frequency_hz = _peak_frequency(aligned, sample_rate)
    snr_db = _snr(source, aligned)
    failures = []
    if amplitude < MIN_AMPLITUDE:
        failures.append("amplitude")
    if correlation < MIN_CORRELATION:
        failures.append("correlation")
    if abs(peak_frequency_hz - expected_frequency_hz) > MAX_FREQUENCY_ERROR_HZ:
        failures.append("frequency")
    if snr_db < MIN_SNR_DB:
        failures.append("snr")
    return Measurement(
        correlation=correlation,
        peak_frequency_hz=peak_frequency_hz,
        snr_db=snr_db,
        amplitude=amplitude,
        passed=not failures,
        failures=tuple(failures),
    )


def verification_result(positive: Measurement, negative: Measurement) -> dict:
    if not positive.passed:
        return {"status": "failed", "reason": "positive_control_failed", "positive": asdict(positive), "negative": asdict(negative)}
    if negative.passed:
        return {"status": "failed", "reason": "negative_control_passed", "positive": asdict(positive), "negative": asdict(negative)}
    return {"status": "passed", "mode": "standard", "positive": asdict(positive), "negative": asdict(negative)}
