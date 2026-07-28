#!/usr/bin/env python3
"""Persist objective Virtual Audio Device loopback evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from scripts.audio_loopback_analysis import measure, verification_result


def write_pcm(path: Path, samples: np.ndarray) -> None:
    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    path.write_bytes((clipped * 32767).astype("<i2").tobytes())


def read_pcm(path: Path) -> np.ndarray:
    return np.frombuffer(path.read_bytes(), dtype="<i2").astype(np.float64) / 32767


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_evidence(
    artifact_dir: Path,
    source: np.ndarray,
    positive: np.ndarray,
    negative: np.ndarray,
    *,
    sample_rate: int,
) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "source.pcm": source,
        "positive.pcm": positive,
        "negative.pcm": negative,
    }
    for name, samples in files.items():
        write_pcm(artifact_dir / name, samples)
    result = verification_result(
        measure(source, positive, sample_rate=sample_rate),
        measure(source, negative, sample_rate=sample_rate),
    )
    result["sample_rate"] = sample_rate
    result["sha256"] = {name: _sha256(artifact_dir / name) for name in files}
    report_path = artifact_dir / "result.json"
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return report_path
